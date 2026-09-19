"""Incremental, crash-safe world and batch writing (``docs/DECISIONS.md#d-011``).

A world is written into ``.world_XXXXXX.partial/`` and renamed to
``world_XXXXXX/`` only once ``manifest.json`` is in place.  A partial directory
is therefore never mistaken for a finished world, and a crash or a single bad
parameter combination cannot damage worlds that already completed.
"""

from __future__ import annotations

import json
import shutil
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from .. import GENERATOR_VERSION, MODEL_BANNER
from ..config import ScenarioConfig
from ..rng import SeedRegistry
from .manifest import HIDDEN, PLANNER_VISIBLE, ManifestBuilder
from .tables import Table

if TYPE_CHECKING:  # import-time cycle: observations.process needs storage.tables
    from ..nature.world import NatureTruth
    from ..observations.process import ObservationBundle


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and not np.isfinite(value):  # pragma: no cover
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _write_npy(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, array, allow_pickle=False)


class WorldWriter:
    """Writes one world atomically into ``root``."""

    def __init__(self, root: str | Path, world_id: int) -> None:
        self.root = Path(root)
        self.world_id = int(world_id)
        self.final_dir = self.root / f"world_{self.world_id:06d}"
        self.partial_dir = self.root / f".world_{self.world_id:06d}.partial"

    def write(
        self,
        *,
        cfg: ScenarioConfig,
        truth: "NatureTruth",
        observations: "ObservationBundle",
        seeds: SeedRegistry,
    ) -> Path:
        """Write the world and return its final directory."""
        if self.partial_dir.exists():
            shutil.rmtree(self.partial_dir)
        if self.final_dir.exists():
            shutil.rmtree(self.final_dir)
        self.partial_dir.mkdir(parents=True, exist_ok=True)

        mb = ManifestBuilder(
            world_id=self.world_id,
            world_dir=self.partial_dir,
            scenario_name=cfg.name,
            config_hash=cfg.config_hash(),
            generator_version=GENERATOR_VERSION,
        )
        d = self.partial_dir

        # ---------------- hidden truth ----------------
        _write_npy(d / "truth/arrival_time_min.npy", truth.arrival_time_min.astype(np.float32))
        mb.add("truth/arrival_time_min.npy", HIDDEN, "Fire arrival time per cell, minutes; +inf where never burned.")

        _write_npy(d / "truth/burned_mask_final.npy", truth.burned_mask_final)
        mb.add("truth/burned_mask_final.npy", HIDDEN, "Final burned mask at the horizon.")

        _write_npy(d / "truth/landscape/elevation_m.npy", truth.elevation_m.astype(np.float32))
        mb.add("truth/landscape/elevation_m.npy", HIDDEN, "Elevation raster, metres.")
        _write_npy(d / "truth/landscape/fuel_multiplier.npy", truth.fuels.multiplier.astype(np.float32))
        mb.add("truth/landscape/fuel_multiplier.npy", HIDDEN, "Continuous fuel spread multiplier (a hidden model parameter).")
        _write_npy(d / "truth/landscape/fuel_class.npy", truth.fuels.fuel_class)
        mb.add("truth/landscape/fuel_class.npy", HIDDEN, "Integer fuel class (also published as static context).")

        Table.from_columns(
            {
                "t_min": truth.weather.t_min,
                "wind_speed_ms": truth.weather.wind_speed_ms,
                "wind_dir_deg": np.rad2deg(truth.weather.wind_dir_rad) % 360.0,
                "temp_c": truth.weather.temp_c,
                "rh_pct": truth.weather.rh_pct,
            }
        ).to_csv(d / "truth/weather_true.csv")
        mb.add("truth/weather_true.csv", HIDDEN, "True uniform weather series. Never planner-visible at any lag.")

        Table.from_columns(
            {
                "t_min": truth.spread.step_times_min,
                "burned_cells": truth.spread.burned_cells_series,
                "active_cells": truth.spread.active_cells_series,
                "burned_area_ha": truth.spread.burned_cells_series
                * truth.grid.cell_area_m2
                / 1e4,
            }
        ).to_csv(d / "truth/active_area_series.csv")
        mb.add("truth/active_area_series.csv", HIDDEN, "Burned and actively-burning cell counts per simulation step.")

        _write_json(
            d / "truth/ignitions.json",
            {
                "initial": truth.initial_ignitions,
                "spot_events": [e.to_dict() for e in truth.spot_events],
                "n_spot_ignited": sum(1 for e in truth.spot_events if e.ignited),
            },
        )
        mb.add("truth/ignitions.json", HIDDEN, "Initial ignitions and every spotting attempt.")

        _write_json(
            d / "truth/nature_params.json",
            {**truth.params, "scenario_config": cfg.to_dict(), "flags": truth.flags},
        )
        mb.add("truth/nature_params.json", HIDDEN, "All hidden nature parameters, the full config, and every seed.")

        _write_json(d / "truth/observation_params.json", observations.hidden_params)
        mb.add("truth/observation_params.json", HIDDEN, "Hidden generative parameters of the observation process.")

        observations.detection_ledger.to_csv(d / "truth/detection_ledger.csv")
        mb.add("truth/detection_ledger.csv", HIDDEN, "Which detections were real and which were spurious.")

        observations.sensor_state.to_csv(d / "truth/sensor_state.csv")
        mb.add("truth/sensor_state.csv", HIDDEN, "True sensor/station down intervals and their causes.")

        # ---------------- planner-visible observations ----------------
        observations.fire_detections.to_csv(d / "observations/fire_detections.csv")
        mb.add("observations/fire_detections.csv", PLANNER_VISIBLE, "Fire detections. Usable only at or after availability_time_min.")

        observations.fire_scan_log.to_csv(d / "observations/fire_scan_log.csv")
        mb.add("observations/fire_scan_log.csv", PLANNER_VISIBLE, "Every scan, including empty ones and outages.")

        observations.weather_observations.to_csv(d / "observations/weather_station_obs.csv")
        mb.add("observations/weather_station_obs.csv", PLANNER_VISIBLE, "Weather station measurements with independent error.")

        _write_json(
            d / "observations/station_metadata.json",
            {"stations": observations.station_metadata},
        )
        mb.add("observations/station_metadata.json", PLANNER_VISIBLE, "Station identifiers and positions (legitimately known).")

        _write_json(d / "observations/sensor_specs_published.json", observations.published_specs)
        mb.add("observations/sensor_specs_published.json", PLANNER_VISIBLE, "Nominal published sensor specifications only.")

        _write_npy(d / "observations/static_context/elevation_m.npy", truth.elevation_m.astype(np.float32))
        mb.add("observations/static_context/elevation_m.npy", PLANNER_VISIBLE, "Static terrain: known before the incident, no temporal content (docs/DECISIONS.md#d-006).")
        _write_npy(d / "observations/static_context/fuel_class.npy", truth.fuels.fuel_class)
        mb.add("observations/static_context/fuel_class.npy", PLANNER_VISIBLE, "Coarse fuel class only; the continuous multiplier stays hidden.")

        # ---------------- metadata ----------------
        metadata = {
            "world_id": self.world_id,
            "scenario_name": cfg.name,
            "description": cfg.description,
            "tags": list(cfg.tags),
            "generator_version": GENERATOR_VERSION,
            "model_banner": MODEL_BANNER,
            "config_hash": cfg.config_hash(),
            "epoch_utc": cfg.epoch,
            "grid": asdict(cfg.grid),
            "time": asdict(cfg.time),
            "horizon_min": cfg.time.horizon_min,
            "flags": truth.flags,
            "warnings": truth.warnings,
            "counts": {
                "n_fire_detections": len(observations.fire_detections),
                "n_fire_scans": len(observations.fire_scan_log),
                "n_weather_obs": len(observations.weather_observations),
                "n_stations": len(observations.station_metadata),
            },
            "note": (
                "Planner-visible. Contains identifiers, geometry and the time "
                "window only -- no nature parameter, no seed, no fire state."
            ),
        }
        _write_json(d / "metadata/world_metadata.json", metadata)
        mb.add("metadata/world_metadata.json", PLANNER_VISIBLE, "World identifiers, geometry and time window.")

        # The summary aggregates hidden truth (burned area, spot count), so it
        # is written under truth/ and labelled hidden -- never into
        # manifest.json, which must stay a pure inventory.  This keeps the
        # access rule crisp: inside a world, a planner may read observations/
        # and metadata/, and nothing else.
        summary = world_summary(cfg, truth, observations, seeds)
        _write_json(d / "truth/world_summary.json", summary)
        mb.add("truth/world_summary.json", HIDDEN, "Aggregate statistics over hidden truth and the observation streams.")

        _write_json(
            d / "manifest.json",
            mb.build(flags=truth.flags, warnings=truth.warnings),
        )

        self.partial_dir.replace(self.final_dir)
        return self.final_dir


def world_summary(
    cfg: ScenarioConfig,
    truth: "NatureTruth",
    observations: "ObservationBundle",
    seeds: SeedRegistry,
) -> dict[str, Any]:
    """Aggregate statistics for one world.

    Written to ``truth/world_summary.json`` (hidden) and copied into the
    batch-level ``batch_index.jsonl``, so that ``wg-osse summarize`` can
    describe hundreds of worlds without reloading their rasters.  Both are
    experimenter-facing artifacts, not planner-facing ones.
    """
    n_det = len(observations.fire_detections)
    ledger = observations.detection_ledger.columns
    kinds = ledger.get("kind")
    n_fp = int(np.count_nonzero(kinds == "false_positive")) if kinds is not None and len(kinds) else 0
    scan_status = observations.fire_scan_log.columns.get("status")
    n_outage = (
        int(np.count_nonzero(scan_status == "outage"))
        if scan_status is not None and len(scan_status)
        else 0
    )
    detect = observations.fire_detections.columns
    if n_det:
        latency = detect["availability_time_min"].astype(float) - detect[
            "event_time_min"
        ].astype(float)
        latency_stats = {
            "min": float(latency.min()),
            "median": float(np.median(latency)),
            "max": float(latency.max()),
        }
    else:
        latency_stats = {"min": None, "median": None, "max": None}

    return {
        "burned_area_ha": truth.burned_area_ha(),
        "burned_fraction": float(np.count_nonzero(truth.burned_mask_final))
        / float(truth.grid.nx * truth.grid.ny),
        "n_spot_ignitions": sum(1 for e in truth.spot_events if e.ignited),
        "n_fire_detections": n_det,
        "n_false_positive_detections": n_fp,
        "n_scans": len(observations.fire_scan_log),
        "n_outage_scans": n_outage,
        "n_weather_obs": len(observations.weather_observations),
        "first_available_detection_min": (
            None
            if not np.isfinite(observations.first_available_detection_min())
            else observations.first_available_detection_min()
        ),
        "detection_latency_min": latency_stats,
        "max_courant": truth.spread.max_courant,
        "sweep_axes": {
            "wind_speed_ms": cfg.weather.wind_speed_ms,
            "wind_dir_deg": cfg.weather.wind_dir_deg,
            "spread_multiplier": cfg.nature.spread_multiplier,
            "spotting_enabled": cfg.nature.spotting.enabled,
            "missingness_mode": cfg.observations.missingness.mode,
        },
        "master_seed": seeds.master_seed,
    }


class BatchWriter:
    """Runs a sequence of worlds, surviving individual failures."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "batch_index.jsonl"
        self.failures_path = self.root / "failures.jsonl"

    def record_success(self, world_id: int, world_dir: Path, summary: dict) -> None:
        self._append(
            self.index_path,
            {"world_id": world_id, "path": world_dir.name, "summary": summary},
        )

    def record_failure(self, world_id: int, scenario_name: str, exc: BaseException) -> None:
        """Log a failure and keep going -- completed worlds must survive."""
        self._append(
            self.failures_path,
            {
                "world_id": world_id,
                "scenario_name": scenario_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            },
        )
        partial = self.root / f".world_{world_id:06d}.partial"
        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)

    @staticmethod
    def _append(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, default=_json_default) + "\n")


def write_world(
    root: str | Path,
    world_id: int,
    *,
    cfg: ScenarioConfig,
    truth: "NatureTruth",
    observations: "ObservationBundle",
    seeds: SeedRegistry,
) -> Path:
    """Convenience wrapper around :class:`WorldWriter`."""
    return WorldWriter(root, world_id).write(
        cfg=cfg, truth=truth, observations=observations, seeds=seeds
    )
