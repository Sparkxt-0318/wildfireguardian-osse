"""World generation for the forecast-value experiment.

A **world** is ``(landscape archetype, terrain, fuels, ignition, weather
sequence, nature randomness)``.  The village, residents, roads and routes are
**nested** inside a world and are never counted as independent units
(``PROTOCOL.md`` section 3).

Splits are by **archetype**, so no geography appears in two splits and tuning
cannot leak into the final evaluation.

Every generation distribution is declared here and classified in
:func:`world_generation_audit` as DATA-INFORMED, ASSUMED or STRESS-TEST.  None
is DATA-INFORMED: nothing in this repository is constrained by Korean data, and
calling a synthetic distribution Korean would be false
(``docs/ASSUMPTIONS.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..config import ScenarioConfig
from ..landscape.grid import Grid
from ..missions.village import WorldGeometry, build_geometry
from ..rng import SeedRegistry

WORLD_GENERATOR_VERSION = "mve-worlds-1.0.0"

#: Domain and time window.  Sized so a wind-driven fire has room to run at the
#: village without leaving the domain in most worlds, and so the whole sweep
#: stays inside the propagation validity envelope (``docs/VALIDATION.md#4``).
GRID = {"nx": 192, "ny": 192, "cell_size_m": 30.0}
TIME = {"horizon_min": 180.0, "dt_min": 1.0}

#: Wind speeds stay at or below 6 m/s: above that the stencil under-predicts
#: burned area and can make it non-monotone in wind, which would be an artefact
#: indistinguishable from a finding (``docs/DECISIONS.md#d-016``).
WIND_SPEED_CHOICES_MS = (2.0, 3.0, 4.0, 5.0, 6.0)
SPREAD_MULTIPLIER_RANGE = (0.85, 1.25)
WIND_SHIFT_PROBABILITY = 0.5
WIND_SHIFT_DEG = 40.0
SPOTTING_PROBABILITY = 0.4

#: Landscape archetypes.  Each fixes terrain and fuel structure.
ARCHETYPES: dict[str, dict[str, Any]] = {
    "plain_uniform": {
        "terrain": {"kind": "flat"},
        "fuels": {"kind": "uniform", "base_multiplier": 1.0},
    },
    "slope_uniform": {
        "terrain": {"kind": "plane", "slope_deg": 18.0, "aspect_deg": 30.0},
        "fuels": {"kind": "uniform", "base_multiplier": 1.0},
    },
    "plain_patchy": {
        "terrain": {"kind": "flat"},
        "fuels": {"kind": "patchy", "patch_scale_m": 600.0, "patch_low": 0.55, "patch_high": 1.3},
    },
    "ridge_along": {
        "terrain": {"kind": "ridge", "relief_m": 200.0, "aspect_deg": 0.0, "ridge_width_m": 900.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 600.0, "patch_low": 0.55, "patch_high": 1.3},
    },
    "ridge_cross": {
        "terrain": {"kind": "ridge", "relief_m": 200.0, "aspect_deg": 90.0, "ridge_width_m": 900.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 500.0, "patch_low": 0.5, "patch_high": 1.35},
    },
    "slope_patchy": {
        "terrain": {"kind": "plane", "slope_deg": 22.0, "aspect_deg": 120.0},
        "fuels": {"kind": "patchy", "patch_scale_m": 500.0, "patch_low": 0.5, "patch_high": 1.35},
    },
}

#: Split by archetype: geography never crosses a split boundary.
SPLITS: dict[str, tuple[str, ...]] = {
    "development": ("plain_uniform", "slope_uniform"),
    "validation": ("plain_patchy", "ridge_along"),
    "final": ("ridge_cross", "slope_patchy"),
}


def split_of(archetype: str) -> str:
    for name, members in SPLITS.items():
        if archetype in members:
            return name
    raise KeyError(f"archetype {archetype!r} belongs to no split")


@dataclass(frozen=True)
class ExperimentWorld:
    """One independent unit of the experiment."""

    world_id: int
    event_id: str
    archetype: str
    split: str
    config: ScenarioConfig
    geometry: WorldGeometry
    seeds: SeedRegistry

    def provenance(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "event_id": self.event_id,
            "archetype": self.archetype,
            "split": self.split,
            "config_hash": self.config.config_hash(),
            "master_seed": self.seeds.master_seed,
            "world_generator_version": WORLD_GENERATOR_VERSION,
        }


def build_experiment_world(
    world_id: int, archetype: str, master_seed: int
) -> ExperimentWorld:
    """Build one world from the declared generation rules."""
    if archetype not in ARCHETYPES:
        raise KeyError(f"unknown archetype {archetype!r}")

    seeds = SeedRegistry.build(master_seed, world_id)
    draw = seeds.generator("nature_seed", "world_design")

    wind_speed = float(draw.choice(WIND_SPEED_CHOICES_MS))
    wind_dir = float(draw.uniform(0.0, 360.0))
    spread_multiplier = float(draw.uniform(*SPREAD_MULTIPLIER_RANGE))
    shifts = bool(draw.random() < WIND_SHIFT_PROBABILITY)
    spotting = bool(draw.random() < SPOTTING_PROBABILITY)

    grid = Grid(nx=GRID["nx"], ny=GRID["ny"], cell_size_m=GRID["cell_size_m"])
    geometry = build_geometry(
        grid, wind_dir_deg=wind_dir, rng=seeds.generator("nature_seed", "geometry")
    )

    weather: dict[str, Any] = {
        "wind_speed_ms": wind_speed,
        "wind_dir_deg": wind_dir,
        "speed_sigma_ms": 0.7,
        "dir_sigma_deg": 12.0,
        "temp_c": 19.0,
        "rh_pct": 32.0,
        "temp_sigma_c": 0.8,
        "rh_sigma_pct": 4.0,
    }
    if shifts:
        veer = float(draw.choice((-WIND_SHIFT_DEG, WIND_SHIFT_DEG)))
        half = TIME["horizon_min"] / 2.0
        weather["schedule"] = [
            {"t_min": 0.0, "speed_ms": wind_speed, "dir_deg": wind_dir},
            {"t_min": half - 10.0, "speed_ms": wind_speed, "dir_deg": wind_dir},
            {"t_min": half + 10.0, "speed_ms": wind_speed, "dir_deg": wind_dir + veer},
            {"t_min": TIME["horizon_min"], "speed_ms": wind_speed, "dir_deg": wind_dir + veer},
        ]

    payload: dict[str, Any] = {
        # Planner-visible identifiers carry no swept value
        # (``docs/DECISIONS.md#d-013``).
        "name": "forecast_value_mve",
        "description": "Forecast-value MVE world. Parameters are hidden truth.",
        "epoch": "2026-04-01T09:00:00Z",
        "master_seed": int(master_seed),
        "tags": ["forecast_value_mve"],
        "grid": dict(GRID),
        "time": dict(TIME),
        "terrain": dict(ARCHETYPES[archetype]["terrain"]),
        "fuels": dict(ARCHETYPES[archetype]["fuels"]),
        "weather": weather,
        "nature": {
            "r0_base_m_per_min": 3.0,
            "spread_multiplier": spread_multiplier,
            "residence_time_min": 30.0,
            "stencil_max_offset": 2,
            "ignitions": [
                {
                    "x_m": geometry.ignition_xy_m[0],
                    "y_m": geometry.ignition_xy_m[1],
                    "time_min": 0.0,
                }
            ],
            "spotting": {
                "enabled": spotting,
                "interval_min": 10.0,
                "rate_per_ha_per_min": 0.003,
                "median_distance_m": 400.0,
                "p_ignite": 0.5,
            },
        },
        "observations": {
            "fire_sensors": [
                {
                    "sensor_id": "fire_sensor_a",
                    "pixel_size_m": 300.0,
                    "cadence_min": 10.0,
                    "first_scan_offset_min": 5.0,
                    "p_detect_max": 0.9,
                    "detect_ref_area_m2": 15000.0,
                    "geoloc_sigma_m": 150.0,
                    "false_positive_rate_per_scan": 0.3,
                    "latency": {
                        "processing_latency_min": 3.0,
                        "delivery_latency_min": 1.0,
                        "jitter_mean_min": 0.5,
                    },
                }
            ],
            "weather_network": {
                "network_id": "wx_net_a",
                "layout": {"kind": "grid", "count": 9, "margin_frac": 0.15},
                "cadence_min": 10.0,
                "sigma_speed_ms": 0.7,
                "sigma_dir_deg": 14.0,
                "latency": {
                    "processing_latency_min": 1.0,
                    "delivery_latency_min": 1.0,
                    "jitter_mean_min": 0.5,
                },
            },
            "missingness": {
                "mode": "correlated_outage",
                "p_fail": 0.05,
                "p_repair": 0.35,
                "tick_min": 20.0,
            },
        },
    }

    return ExperimentWorld(
        world_id=world_id,
        event_id=f"{archetype}-{world_id:05d}",
        archetype=archetype,
        split=split_of(archetype),
        config=ScenarioConfig.from_mapping(payload),
        geometry=geometry,
        seeds=seeds,
    )


def build_world_set(
    split: str, n_worlds: int, master_seed: int, world_id_offset: int = 0
) -> list[ExperimentWorld]:
    """Build ``n_worlds`` worlds drawn from a split's archetypes, round-robin."""
    if split not in SPLITS:
        raise KeyError(f"unknown split {split!r}; have {sorted(SPLITS)}")
    archetypes = SPLITS[split]
    return [
        build_experiment_world(
            world_id=world_id_offset + k,
            archetype=archetypes[k % len(archetypes)],
            master_seed=master_seed,
        )
        for k in range(n_worlds)
    ]


def world_generation_audit() -> dict[str, Any]:
    """Declared distributions and their evidential status.

    Nothing here is DATA-INFORMED.  A synthetic distribution must not be called
    Korean unless it is constrained by Korean data, and none of these is
    (``PROTOCOL.md`` section 14; the brief's world-generation audit).
    """
    return {
        "note": (
            "No distribution below is constrained by Korean data. These are "
            "synthetic worlds; results are not Korean-anchored."
        ),
        "distributions": {
            "ignition_location": {
                "rule": (
                    "upwind of the village at "
                    "1100 m +/- 200 m, bearing jitter 30 deg"
                ),
                "status": "STRESS-TEST",
                "caveat": (
                    "Deliberately biases the sample toward threatened villages. "
                    "Without it most worlds would contain no decision problem. "
                    "It is NOT a claim about where fires start."
                ),
            },
            "wind_speed_ms": {
                "rule": f"uniform over {list(WIND_SPEED_CHOICES_MS)}",
                "status": "ASSUMED",
                "caveat": "Capped at 6 m/s by the propagation validity envelope.",
            },
            "wind_direction_deg": {"rule": "uniform over [0, 360)", "status": "ASSUMED"},
            "wind_shifts": {
                "rule": f"{WIND_SHIFT_PROBABILITY:.0%} of worlds veer {WIND_SHIFT_DEG} deg at mid-run",
                "status": "STRESS-TEST",
            },
            "spread_multiplier": {
                "rule": f"uniform over {list(SPREAD_MULTIPLIER_RANGE)}",
                "status": "ASSUMED",
            },
            "fuel_heterogeneity": {
                "rule": "per archetype: uniform, or smoothed value noise 0.5-1.35",
                "status": "ASSUMED",
            },
            "terrain": {
                "rule": "per archetype: flat, planar slope, or Gaussian ridge",
                "status": "ASSUMED",
                "caveat": "Not derived from any DEM (docs/ASSUMPTIONS.md#A-05).",
            },
            "spotting": {
                "rule": f"enabled in {SPOTTING_PROBABILITY:.0%} of worlds",
                "status": "STRESS-TEST",
            },
            "route_topology": {
                "rule": "two evacuation routes, one direct and one detour, plus one approach",
                "status": "ASSUMED",
                "caveat": "Not a real road network; see the Korean anchoring plan.",
            },
            "village_geometry": {
                "rule": "fixed fractions of the domain, identical in every world",
                "status": "ASSUMED",
                "caveat": (
                    "Village, destination and base do not vary between worlds, so "
                    "geometric variation comes only from wind direction and "
                    "ignition placement."
                ),
            },
        },
    }
