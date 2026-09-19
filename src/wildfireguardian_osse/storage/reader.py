"""Read-only access to a generated world.

The single most important function here is :func:`available_at`.  A consumer
making a decision at time ``t`` may use exactly the observations whose
``availability_time_min`` is at or before ``t`` -- filtering on
``event_time_min`` instead is the classic way to manufacture optimistic results
(``docs/FAILURE_MODES.md#L-03``).  It is provided so that no consumer has to
write that comparison itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .tables import read_table

#: Directories inside a world that a planner is permitted to read.
PLANNER_READABLE_DIRS: tuple[str, ...] = ("observations", "metadata")


def available_at(table: Mapping[str, np.ndarray], t_min: float) -> dict[str, np.ndarray]:
    """Rows of ``table`` that are legally usable at simulation time ``t_min``.

    Args:
        table: a table read by :func:`~.tables.read_table`.
        t_min: decision time, minutes since ``t0``.

    Returns:
        The same mapping, filtered to ``availability_time_min <= t_min``.

    Raises:
        KeyError: if the table has no ``availability_time_min`` column -- which
            means it is not an observation table and must not be used as one.
    """
    if "availability_time_min" not in table:
        raise KeyError(
            "table has no availability_time_min column; only observation "
            "tables may be filtered for use (docs/TIME_SEMANTICS.md#2)"
        )
    if len(table["availability_time_min"]) == 0:
        return {k: v for k, v in table.items()}
    mask = table["availability_time_min"].astype(float) <= float(t_min)
    return {k: v[mask] for k, v in table.items()}


@dataclass
class World:
    """A loaded world.  Hidden truth is loaded only on explicit request."""

    path: Path
    manifest: dict[str, Any]
    metadata: dict[str, Any]
    fire_detections: dict[str, np.ndarray]
    fire_scan_log: dict[str, np.ndarray]
    weather_observations: dict[str, np.ndarray]
    station_metadata: list[dict]
    published_specs: dict[str, Any]

    def observations_available_at(self, t_min: float) -> dict[str, dict[str, np.ndarray]]:
        """All planner-facing streams filtered to what is usable at ``t_min``."""
        return {
            "fire_detections": available_at(self.fire_detections, t_min),
            "fire_scan_log": available_at(self.fire_scan_log, t_min),
            "weather_observations": available_at(self.weather_observations, t_min),
        }

    # -- hidden truth: explicit, never implicit --------------------------
    def load_truth_array(self, name: str) -> np.ndarray:
        """Load a hidden truth raster.  **Scoring and analysis only.**

        Calling this from anything acting as a planner invalidates the
        experiment (``docs/OBSERVATION_MODEL.md#0``).
        """
        return np.load(self.path / "truth" / name, allow_pickle=False)

    def load_truth_table(self, name: str) -> dict[str, np.ndarray]:
        """Load a hidden truth table.  **Scoring and analysis only.**"""
        return read_table(self.path / "truth" / name)

    def load_world_summary(self) -> dict[str, Any]:
        """Aggregate statistics.  Experimenter-facing, not planner-facing."""
        return json.loads(
            (self.path / "truth" / "world_summary.json").read_text(encoding="utf-8")
        )


def load_world(path: str | Path) -> World:
    """Load a completed world directory.

    Raises:
        FileNotFoundError: if the directory has no ``manifest.json``, which is
            how an interrupted, partially written world is rejected
            (``docs/DECISIONS.md#d-011``).
    """
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{path} has no manifest.json: it is not a completed world "
            "(a '.partial' directory is an interrupted write)"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = json.loads(
        (path / "metadata/world_metadata.json").read_text(encoding="utf-8")
    )
    stations = json.loads(
        (path / "observations/station_metadata.json").read_text(encoding="utf-8")
    )["stations"]
    specs = json.loads(
        (path / "observations/sensor_specs_published.json").read_text(encoding="utf-8")
    )
    return World(
        path=path,
        manifest=manifest,
        metadata=metadata,
        fire_detections=read_table(path / "observations/fire_detections.csv"),
        fire_scan_log=read_table(path / "observations/fire_scan_log.csv"),
        weather_observations=read_table(path / "observations/weather_station_obs.csv"),
        station_metadata=stations,
        published_specs=specs,
    )
