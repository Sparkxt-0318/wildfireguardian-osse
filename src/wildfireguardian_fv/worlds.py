"""Generation of experiment worlds, under predeclared rules.

The generation rules below are fixed before any result is looked at.  A world
is never rejected because the forecast-aware policy loses in it, because the
frontier is dull, or because the baseline dominates (PROTOCOL.md section 11).
The only rejection rule is a *mechanical* one, declared here: a world whose
nature simulation raises a discretisation warning is regenerated with the next
world index, because such a world's hidden truth is not trustworthy at all.

Every distribution used here is labelled in :data:`GENERATION_AUDIT` as
``DATA-INFORMED``, ``ASSUMED`` or ``STRESS-TEST``.  In this first experiment
**none is DATA-INFORMED**: no Korean (or any other) observational distribution
constrains these worlds, so no world here may be described as Korean.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np

from wildfireguardian_osse.config import ScenarioConfig
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.rng import SeedRegistry

from . import WORLD_GENERATOR_VERSION
from .rng import FvSeedRegistry
from .splits import ARCHETYPE_SPLIT, note_final_split_read, split_of
from .village import VillageConfig, build_village
from .world import ExperimentWorld

#: Provenance of every generation distribution.  Read by the world-generation
#: audit in ``reports/MVE_METHOD.md``.
GENERATION_AUDIT: dict[str, dict[str, str]] = {
    "ignition_distance_m": {
        "class": "ASSUMED",
        "spec": "Uniform(1400, 3000) from the village centre",
        "why": "Chosen so the fire-to-village race is decidable within the "
        "horizon at the modelled spread rates. No observational basis.",
    },
    "ignition_bearing_deg": {
        "class": "ASSUMED",
        "spec": "Upwind bearing from the village +/- Uniform(-70, 70) deg",
        "why": "Biases towards worlds where the village is downwind, without "
        "guaranteeing it: a substantial fraction of worlds never threaten the "
        "village, which is what makes unnecessary dispatch measurable.",
    },
    "wind_speed_ms": {
        "class": "STRESS-TEST",
        "spec": "Uniform(2.5, 6.0) m/s, constant or a single shift",
        "why": "Upper bound is the laboratory's validated stencil limit "
        "(docs/VALIDATION.md#4), not a meteorological statement.",
    },
    "wind_direction_deg": {
        "class": "ASSUMED",
        "spec": "Uniform(0, 360) deg (direction the wind blows toward, CCW "
        "from east)",
        "why": "No regime information is available, so the least-committal "
        "choice is used.",
    },
    "wind_shift": {
        "class": "STRESS-TEST",
        "spec": "35% of worlds shift direction by Uniform(35, 85) deg at a "
        "time in the middle third of the horizon",
        "why": "Creates the forecast-relevant mechanism (a turn the planner "
        "cannot see coming) at a declared rate; the rate is not an estimate of "
        "how often real wind shifts.",
    },
    "fuel_heterogeneity": {
        "class": "ASSUMED",
        "spec": "Per-archetype: patchy lognormal-like patches, or a "
        "non-burnable band",
        "why": "Transparent synthetic heterogeneity; no fuel map is used.",
    },
    "terrain": {
        "class": "ASSUMED",
        "spec": "Per-archetype: flat / planar slope / ridge / smooth noise",
        "why": "Synthetic. No DEM is used (PROTOCOL.md section 14).",
    },
    "spotting": {
        "class": "STRESS-TEST",
        "spec": "Enabled in 40% of worlds at the laboratory default rate",
        "why": "Spotting is one of the two mechanisms the experiment studies; "
        "its prevalence here is a design choice, not a measured frequency.",
    },
    "route_topology": {
        "class": "ASSUMED",
        "spec": "Perturbed 6x6 lattice, 72% of minor edges retained, "
        "connectivity restored deterministically",
        "why": "A lattice is transparent and gives alternative routes. Rural "
        "Korean road networks are dendritic, not lattices -- recorded as a "
        "limitation.",
    },
    "village_geometry": {
        "class": "ASSUMED",
        "spec": "6 houses within 900 m of the domain centre; base at one "
        "corner; two destinations at far corners",
        "why": "Terrain-independent placement. No village archetype data is "
        "used.",
    },
    "resident_capability": {
        "class": "ASSUMED",
        "spec": "Bernoulli(0.45) self-evacuation capable, independent of route "
        "existence",
        "why": "Capability is an assumption about people, never an inference "
        "from the road graph (PROTOCOL.md section 6).",
    },
}

#: Landscape/fuel families.  Each belongs to exactly one split
#: (``splits.ARCHETYPE_SPLIT``).
ARCHETYPES: dict[str, dict[str, Any]] = {
    "open_plain": {
        "terrain": {"kind": "flat", "base_elevation_m": 180.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 450.0, "patch_low": 0.5,
                  "patch_high": 1.3},
    },
    "rolling_noise": {
        "terrain": {"kind": "noise", "relief_m": 120.0, "noise_scale_m": 700.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 380.0, "patch_low": 0.45,
                  "patch_high": 1.35},
    },
    "sloped_valley": {
        "terrain": {"kind": "plane", "slope_deg": 12.0, "aspect_deg": 90.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 520.0, "patch_low": 0.55,
                  "patch_high": 1.25},
    },
    "mosaic_barrier": {
        "terrain": {"kind": "noise", "relief_m": 90.0, "noise_scale_m": 550.0},
        "fuels": {"kind": "band", "base_multiplier": 1.0,
                  "band_orientation": "vertical", "band_position_frac": 0.55,
                  "band_width_m": 150.0, "band_multiplier": 0.0},
    },
    "ridge_channel": {
        "terrain": {"kind": "ridge", "relief_m": 200.0, "ridge_width_m": 900.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 430.0, "patch_low": 0.5,
                  "patch_high": 1.3},
    },
    "plateau_step": {
        "terrain": {"kind": "plane", "slope_deg": 6.0, "aspect_deg": 200.0},
        "fuels": {"kind": "band", "base_multiplier": 1.0,
                  "band_orientation": "horizontal", "band_position_frac": 0.45,
                  "band_width_m": 120.0, "band_multiplier": 0.25},
    },
}

assert set(ARCHETYPES) == set(ARCHETYPE_SPLIT), "archetype tables disagree"


@dataclass(frozen=True)
class WorldGenConfig:
    """Declared generation parameters.  Frozen before the experiment runs."""

    nx: int = 192
    ny: int = 192
    cell_size_m: float = 30.0
    horizon_min: float = 240.0
    dt_min: float = 1.0
    master_seed: int = 20260920
    fire_cadence_min: float = 15.0
    p_detect_max: float = 0.90
    geoloc_sigma_m: float = 150.0
    p_spotting: float = 0.40
    p_wind_shift: float = 0.35
    wind_speed_lo_ms: float = 2.5
    wind_speed_hi_ms: float = 6.0
    ignition_dist_lo_m: float = 1400.0
    ignition_dist_hi_m: float = 3000.0
    ignition_bearing_jitter_deg: float = 70.0
    village: VillageConfig = VillageConfig()
    max_regeneration_attempts: int = 6

    @property
    def width_m(self) -> float:
        return self.nx * self.cell_size_m

    @property
    def height_m(self) -> float:
        return self.ny * self.cell_size_m


def _scenario_payload(
    gen: WorldGenConfig,
    archetype: str,
    world_id: int,
    wind_speed_ms: float,
    wind_dir_deg: float,
    shift: tuple[float, float] | None,
    ignition_xy_m: tuple[float, float],
    spotting: bool,
) -> dict[str, Any]:
    arch = ARCHETYPES[archetype]
    weather: dict[str, Any] = {
        "wind_speed_ms": float(wind_speed_ms),
        "wind_dir_deg": float(wind_dir_deg),
        "speed_sigma_ms": 0.6,
        "dir_sigma_deg": 9.0,
    }
    if shift is not None:
        t_shift, new_dir = shift
        weather["schedule"] = [
            {"t_min": 0.0, "speed_ms": float(wind_speed_ms),
             "dir_deg": float(wind_dir_deg)},
            {"t_min": float(t_shift), "speed_ms": float(wind_speed_ms),
             "dir_deg": float(wind_dir_deg)},
            {"t_min": float(min(t_shift + 20.0, gen.horizon_min)),
             "speed_ms": float(wind_speed_ms), "dir_deg": float(new_dir)},
            {"t_min": float(gen.horizon_min), "speed_ms": float(wind_speed_ms),
             "dir_deg": float(new_dir)},
        ]
    return {
        "name": f"fv_{archetype}_{world_id:04d}",
        "description": (
            f"Forecast-value experiment world ({archetype}); synthetic, "
            "not Korean-anchored."
        ),
        "tags": ["forecast_value_mve", archetype, split_of(archetype)],
        "master_seed": int(gen.master_seed),
        "grid": {"nx": gen.nx, "ny": gen.ny, "cell_size_m": gen.cell_size_m},
        "time": {"horizon_min": gen.horizon_min, "dt_min": gen.dt_min},
        "terrain": dict(arch["terrain"]),
        "fuels": dict(arch["fuels"]),
        "weather": weather,
        "nature": {
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [
                {"x_m": float(ignition_xy_m[0]), "y_m": float(ignition_xy_m[1]),
                 "time_min": 0.0}
            ],
            "spotting": {"enabled": bool(spotting)},
        },
        "observations": {
            "fire_sensors": [
                {
                    "sensor_id": "fire_sensor_a",
                    "pixel_size_m": 375.0,
                    "cadence_min": gen.fire_cadence_min,
                    "first_scan_offset_min": 5.0,
                    "p_detect_max": gen.p_detect_max,
                    "geoloc_sigma_m": gen.geoloc_sigma_m,
                    "latency": {
                        "acquisition_offset_min": 0.0,
                        "processing_latency_min": 5.0,
                        "delivery_latency_min": 2.0,
                        "jitter_mean_min": 1.0,
                    },
                }
            ],
            "weather_network": {"network_id": "wx_net_a", "cadence_min": 10.0},
            "missingness": {"mode": "mcar", "p_missing": 0.05},
        },
    }


def build_experiment_world(
    gen: WorldGenConfig, archetype: str, world_id: int
) -> ExperimentWorld:
    """Generate one experiment world.

    Order matters and is fixed: the village is laid out **first**, from the
    experiment-side ``world_layout_seed`` stream, and the ignition is then
    placed relative to it.  The reverse order would make the village position
    a function of the hidden fire.

    The planner knows the village, and therefore knows the *distribution* the
    ignition was drawn from.  That is shared by both policies and carries no
    per-world information; it is recorded in LEAKAGE_AUDIT.md section 5 rather
    than hidden.

    Raises:
        RuntimeError: if every regeneration attempt produced a world the
            laboratory itself flagged as discretisation-unsound.
    """
    if archetype not in ARCHETYPES:
        raise ValueError(f"unknown archetype {archetype!r}")
    split = split_of(archetype)
    if split == "final":
        note_final_split_read(f"build_experiment_world({archetype}, {world_id})")

    for attempt in range(int(gen.max_regeneration_attempts)):
        effective_id = world_id + 10_000 * attempt
        fv_seeds = FvSeedRegistry.build(gen.master_seed, effective_id)
        village = build_village(
            gen.village,
            gen.width_m,
            gen.height_m,
            fv_seeds.generator("world_layout_seed", "village"),
            village_id=f"v{world_id:04d}",
        )

        wx = fv_seeds.generator("world_layout_seed", "weather_regime")
        wind_speed = float(wx.uniform(gen.wind_speed_lo_ms, gen.wind_speed_hi_ms))
        wind_dir_deg = float(wx.uniform(0.0, 360.0))
        shift = None
        if float(wx.random()) < gen.p_wind_shift:
            t_shift = float(wx.uniform(gen.horizon_min / 3.0, 2.0 * gen.horizon_min / 3.0))
            delta = float(wx.uniform(35.0, 85.0)) * (1.0 if wx.random() < 0.5 else -1.0)
            shift = (t_shift, (wind_dir_deg + delta) % 360.0)
        spotting = bool(wx.random() < gen.p_spotting)

        ig = fv_seeds.generator("ignition_seed", "placement")
        distance = float(ig.uniform(gen.ignition_dist_lo_m, gen.ignition_dist_hi_m))
        jitter = float(ig.uniform(-gen.ignition_bearing_jitter_deg,
                                  gen.ignition_bearing_jitter_deg))
        # Upwind of the village: the wind blows *toward* wind_dir_deg, so the
        # upwind side is at wind_dir_deg + 180.
        bearing = math.radians(wind_dir_deg + 180.0 + jitter)
        cx, cy = village.centre_xy_m
        ign_x = float(np.clip(cx + distance * math.cos(bearing),
                              2.0 * gen.cell_size_m, gen.width_m - 2.0 * gen.cell_size_m))
        ign_y = float(np.clip(cy + distance * math.sin(bearing),
                              2.0 * gen.cell_size_m, gen.height_m - 2.0 * gen.cell_size_m))

        payload = _scenario_payload(
            gen, archetype, world_id, wind_speed, wind_dir_deg, shift,
            (ign_x, ign_y), spotting,
        )
        cfg: ScenarioConfig = ScenarioConfig.from_mapping(payload)
        generated = generate_world(cfg, world_id=effective_id)
        if generated.truth.warnings:
            continue

        audit = {
            "archetype": archetype,
            "split": split,
            "attempt": attempt,
            "wind_speed_ms": wind_speed,
            "wind_dir_deg": wind_dir_deg,
            "wind_shift": None if shift is None else {"t_min": shift[0],
                                                      "new_dir_deg": shift[1]},
            "spotting_enabled": spotting,
            "ignition_distance_m": distance,
            "ignition_bearing_offset_deg": jitter,
            "ignition_xy_m": [ign_x, ign_y],
            "n_spot_events": len(generated.truth.spot_events),
            "burned_area_ha": generated.truth.burned_area_ha(),
            "world_generator_version": WORLD_GENERATOR_VERSION,
        }
        return ExperimentWorld(
            world_id=world_id,
            event_id=f"{archetype}-{world_id:04d}",
            split=split,
            archetype=archetype,
            config=cfg,
            lab_seeds=SeedRegistry.build(cfg.master_seed, effective_id),
            fv_seeds=fv_seeds,
            truth=generated.truth,
            observations=generated.observations,
            village=village,
            static_context={
                "elevation_m": generated.truth.elevation_m.astype(np.float32),
                "fuel_class": generated.truth.fuels.fuel_class,
            },
            grid_meta={
                "nx": cfg.grid.nx,
                "ny": cfg.grid.ny,
                "cell_size_m": cfg.grid.cell_size_m,
                "width_m": gen.width_m,
                "height_m": gen.height_m,
                "epoch_utc": cfg.epoch,
                "config_hash": cfg.config_hash(),
            },
            horizon_min=float(cfg.time.horizon_min),
            generation_audit=audit,
        )
    raise RuntimeError(
        f"world {world_id} ({archetype}) failed {gen.max_regeneration_attempts} "
        "discretisation checks; widen the stencil or narrow the wind range"
    )


def generate_split(
    gen: WorldGenConfig, split: str, n_worlds: int, start_index: int = 0
) -> Iterator[ExperimentWorld]:
    """Yield ``n_worlds`` worlds for ``split``, cycling its archetypes evenly."""
    from .splits import archetypes_for

    archetypes = archetypes_for(split)
    for k in range(int(n_worlds)):
        archetype = archetypes[k % len(archetypes)]
        yield build_experiment_world(gen, archetype, start_index + k)
