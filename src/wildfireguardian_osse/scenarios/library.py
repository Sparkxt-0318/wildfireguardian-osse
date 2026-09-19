"""The eight validation worlds (``docs/VALIDATION.md#1``).

Note that ``name`` and ``description`` are **planner-visible**: they end up in
``metadata/world_metadata.json``.  They therefore describe each world
qualitatively and never quote a parameter value; the numbers live in
``docs/VALIDATION.md`` and in hidden truth (``docs/DECISIONS.md#d-013``).

Defined in Python so that they are importable however the package is installed,
and exported to ``experiments/manifests/validation/*.yaml`` by
``wg-osse export-scenarios`` so that they are also readable as data.  The
Python definitions are the source of truth; the YAML files are artifacts.

Each scenario is deliberately minimal: it changes only what its expectation
depends on, so that a failure points at one mechanism.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from ..config import ScenarioConfig

# The domain is sized so that no validation world reaches its boundary: a
# clipped fire invalidates every shape expectation in docs/VALIDATION.md, and
# the flag that detects it (``boundary_contact``) is asserted absent by the
# validation tests rather than tolerated.
_GRID = {"nx": 192, "ny": 192, "cell_size_m": 30.0}
_WIDTH = _GRID["nx"] * _GRID["cell_size_m"]
_CENTRE = _WIDTH / 2.0
#: Ignition well upwind of the eastern edge, for the wind-driven scenarios.
_UPWIND = (_WIDTH * 0.2, _CENTRE)
_TIME = {"horizon_min": 180.0, "dt_min": 1.0}

#: A clean observation configuration: frequent, accurate, complete.  Validation
#: worlds test the *nature* model, so their observation process is made as
#: transparent as possible unless the scenario is specifically about it.
_CLEAN_OBS: dict[str, Any] = {
    "fire_sensors": [
        {
            "sensor_id": "fire_sensor_a",
            "pixel_size_m": 300.0,
            "cadence_min": 15.0,
            "first_scan_offset_min": 5.0,
            "p_detect_max": 0.95,
            "detect_ref_area_m2": 10000.0,
            "geoloc_sigma_m": 60.0,
            "false_positive_rate_per_scan": 0.0,
            "latency": {
                "processing_latency_min": 4.0,
                "delivery_latency_min": 2.0,
                "jitter_mean_min": 0.5,
            },
        }
    ],
    "weather_network": {
        "network_id": "wx_net_a",
        "layout": {"kind": "grid", "count": 9},
        "cadence_min": 10.0,
    },
    "missingness": {"mode": "none"},
}


def _base(name: str, description: str, **overrides: Any) -> dict[str, Any]:
    scenario: dict[str, Any] = {
        "name": name,
        "description": description,
        "epoch": "2026-04-01T09:00:00Z",
        "master_seed": 20260401,
        "tags": ["validation"],
        "grid": copy.deepcopy(_GRID),
        "time": copy.deepcopy(_TIME),
        "terrain": {"kind": "flat"},
        "fuels": {"kind": "uniform", "base_multiplier": 1.0},
        "weather": {"wind_speed_ms": 0.0, "wind_dir_deg": 0.0},
        "nature": {
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [{"x_m": _CENTRE, "y_m": _CENTRE, "time_min": 0.0}],
            "spotting": {"enabled": False},
        },
        "observations": copy.deepcopy(_CLEAN_OBS),
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(scenario.get(key), dict):
            scenario[key] = {**scenario[key], **value}
        else:
            scenario[key] = value
    return scenario


#: Name -> scenario mapping.  Ordered V1..V8 as in ``docs/VALIDATION.md``.
VALIDATION_SCENARIOS: dict[str, dict[str, Any]] = {
    "v1_uniform_no_wind": _base(
        "v1_uniform_no_wind",
        "V1: flat, uniform fuel, no wind. Expect isotropic (disc) spread at R0.",
    ),
    "v2_uniform_constant_wind": _base(
        "v2_uniform_constant_wind",
        "V2: flat, uniform fuel, steady wind toward the east. Expect a "
        "downwind-elongated ellipse; see docs/VALIDATION.md for the setup.",
        weather={"wind_speed_ms": 6.0, "wind_dir_deg": 0.0},
        nature={
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [{"x_m": _UPWIND[0], "y_m": _UPWIND[1], "time_min": 0.0}],
            "spotting": {"enabled": False},
        },
    ),
    "v3_slope_only": _base(
        "v3_slope_only",
        "V3: planar slope ascending east, no wind. Expect faster upslope than "
        "downslope spread; see docs/VALIDATION.md for the setup.",
        terrain={"kind": "plane", "slope_deg": 25.0, "aspect_deg": 0.0},
    ),
    "v4_fuel_discontinuity": _base(
        "v4_fuel_discontinuity",
        "V4: uniform fuel crossed by a non-burnable band. Expect exactly zero "
        "burned cells beyond the band.",
        fuels={
            "kind": "band",
            "base_multiplier": 1.0,
            "band_orientation": "vertical",
            "band_position_frac": 0.62,
            "band_width_m": 150.0,
            "band_multiplier": 0.0,
        },
        weather={"wind_speed_ms": 6.0, "wind_dir_deg": 0.0},
    ),
    "v5_wind_shift": _base(
        "v5_wind_shift",
        "V5: the wind veers part-way through the run. Expect the growth "
        "direction to change with it.",
        weather={
            "wind_speed_ms": 6.0,
            "wind_dir_deg": 0.0,
            "schedule": [
                {"t_min": 0.0, "speed_ms": 6.0, "dir_deg": 0.0},
                {"t_min": 89.0, "speed_ms": 6.0, "dir_deg": 0.0},
                {"t_min": 91.0, "speed_ms": 6.0, "dir_deg": 90.0},
                {"t_min": 180.0, "speed_ms": 6.0, "dir_deg": 90.0},
            ],
        },
        nature={
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [{"x_m": _WIDTH * 0.25, "y_m": _WIDTH * 0.30, "time_min": 0.0}],
            "spotting": {"enabled": False},
        },
    ),
    "v6_spotting_off": _base(
        "v6_spotting_off",
        "V6: as V2 with spotting explicitly disabled. The control for V7.",
        weather={"wind_speed_ms": 6.0, "wind_dir_deg": 0.0},
        nature={
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [{"x_m": _UPWIND[0], "y_m": _UPWIND[1], "time_min": 0.0}],
            "spotting": {"enabled": False},
        },
    ),
    "v7_spotting_on": _base(
        "v7_spotting_on",
        "V7: as V6 with spotting enabled. Expect at least one spot ignition and "
        "a burned area no smaller than V6.",
        weather={"wind_speed_ms": 6.0, "wind_dir_deg": 0.0},
        nature={
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [{"x_m": _UPWIND[0], "y_m": _UPWIND[1], "time_min": 0.0}],
            "spotting": {
                "enabled": True,
                "interval_min": 10.0,
                # Tuned so the spotting-driven fire still finishes inside the
                # domain: a boundary-clipped V7 could not be compared with V6.
                "rate_per_ha_per_min": 0.003,
                "median_distance_m": 400.0,
                "p_ignite": 0.6,
            },
        },
    ),
    "v8_sensor_outage": _base(
        "v8_sensor_outage",
        "V8: as V6 with a correlated sensor outage. The truth must be identical "
        "to V6 -- the outage may touch only the observation layer.",
        weather={"wind_speed_ms": 6.0, "wind_dir_deg": 0.0},
        nature={
            "r0_base_m_per_min": 3.0,
            "residence_time_min": 30.0,
            "ignitions": [{"x_m": _UPWIND[0], "y_m": _UPWIND[1], "time_min": 0.0}],
            "spotting": {"enabled": False},
        },
        observations={
            **copy.deepcopy(_CLEAN_OBS),
            "missingness": {
                "mode": "correlated_outage",
                "p_fail": 0.35,
                "p_repair": 0.25,
                "tick_min": 15.0,
            },
        },
    ),
}


def validation_scenario_names() -> list[str]:
    return list(VALIDATION_SCENARIOS)


def build_validation_scenario(name: str) -> ScenarioConfig:
    """Build and validate one validation scenario by name."""
    if name not in VALIDATION_SCENARIOS:
        raise KeyError(
            f"unknown validation scenario {name!r}; available: "
            f"{validation_scenario_names()}"
        )
    return ScenarioConfig.from_mapping(copy.deepcopy(VALIDATION_SCENARIOS[name]))


def export_scenarios(directory: str | Path) -> list[Path]:
    """Write every validation scenario to ``directory`` as YAML.

    The YAML is an artifact of the Python definitions, regenerated rather than
    hand-edited.
    """
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, payload in VALIDATION_SCENARIOS.items():
        # Round-trip through ScenarioConfig so the file holds the fully
        # defaulted, validated scenario rather than a partial override.
        cfg = ScenarioConfig.from_mapping(copy.deepcopy(payload))
        path = out_dir / f"{name}.yaml"
        header = (
            "# Generated by `wg-osse export-scenarios` from\n"
            "# src/wildfireguardian_osse/scenarios/library.py -- do not hand-edit.\n"
            "# Synthetic nature model for controlled experiments;\n"
            "# not an operational wildfire forecast model.\n"
        )
        path.write_text(
            header + yaml.safe_dump(cfg.to_dict(), sort_keys=True, default_flow_style=False),
            encoding="utf-8",
        )
        written.append(path)
    return written
