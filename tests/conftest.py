"""Shared fixtures.

Tests use small, fast worlds unless a test is specifically about scale.  The
default here is a 64x64 grid over 90 minutes, which generates in well under a
second.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from wildfireguardian_osse.config import ScenarioConfig
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.scenarios.library import VALIDATION_SCENARIOS
from wildfireguardian_osse.storage.writer import WorldWriter

FAST_GRID = {"nx": 64, "ny": 64, "cell_size_m": 30.0}
FAST_TIME = {"horizon_min": 90.0, "dt_min": 1.0}
CENTRE = 64 * 30.0 / 2.0


def fast_scenario(**overrides: Any) -> ScenarioConfig:
    """A small scenario with a wind-driven fire and a noisy, lossy observer."""
    payload: dict[str, Any] = {
        "name": "fast_test_world",
        "description": "small scenario for tests",
        "master_seed": 12345,
        "grid": dict(FAST_GRID),
        "time": dict(FAST_TIME),
        "terrain": {"kind": "flat"},
        "fuels": {"kind": "uniform"},
        "weather": {
            "wind_speed_ms": 4.0,
            "wind_dir_deg": 0.0,
            "speed_sigma_ms": 0.5,
            "dir_sigma_deg": 8.0,
        },
        "nature": {
            "ignitions": [{"x_m": CENTRE * 0.6, "y_m": CENTRE, "time_min": 0.0}],
            "spotting": {"enabled": False},
        },
        "observations": {
            "fire_sensors": [
                {
                    "sensor_id": "fire_sensor_a",
                    "pixel_size_m": 240.0,
                    "cadence_min": 10.0,
                    "p_detect_max": 0.9,
                    "detect_ref_area_m2": 8000.0,
                    "geoloc_sigma_m": 90.0,
                    "false_positive_rate_per_scan": 0.5,
                }
            ],
            "weather_network": {
                "network_id": "wx_net_a",
                "layout": {"kind": "grid", "count": 4},
                "cadence_min": 15.0,
            },
            "missingness": {"mode": "none"},
        },
    }
    _deep_update(payload, overrides)
    return ScenarioConfig.from_mapping(payload)


def _deep_update(target: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def validation_scenario(name: str, **overrides: Any) -> ScenarioConfig:
    payload = copy.deepcopy(VALIDATION_SCENARIOS[name])
    _deep_update(payload, overrides)
    return ScenarioConfig.from_mapping(payload)


def write_world(cfg: ScenarioConfig, root, world_id: int = 0):
    world = generate_world(cfg, world_id)
    return WorldWriter(root, world_id).write(
        cfg=world.config,
        truth=world.truth,
        observations=world.observations,
        seeds=world.seeds,
    )


@pytest.fixture(scope="session")
def fast_world():
    return generate_world(fast_scenario(), 0)


@pytest.fixture()
def written_world(tmp_path):
    """A complete world written to disk."""
    return write_world(fast_scenario(), tmp_path / "batch", 1)
