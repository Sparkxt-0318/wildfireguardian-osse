"""Reproducibility and stream independence (``docs/DECISIONS.md#d-004``)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import fast_scenario, write_world
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.storage.manifest import sha256_file

STOCHASTIC_SCENARIO = dict(
    weather={"wind_speed_ms": 4.0, "speed_sigma_ms": 1.0, "dir_sigma_deg": 20.0},
    nature={
        "spotting": {
            "enabled": True,
            "interval_min": 10.0,
            "rate_per_ha_per_min": 0.02,
            "median_distance_m": 300.0,
            "p_ignite": 0.6,
        }
    },
    observations={
        "fire_sensors": [
            {"sensor_id": "fire_sensor_a", "pixel_size_m": 240.0,
             "cadence_min": 10.0, "false_positive_rate_per_scan": 1.0}
        ],
        "missingness": {"mode": "mcar", "p_missing": 0.2},
    },
)


def _checksums(world_dir, prefix: str | None = None) -> dict[str, str]:
    manifest = json.loads((world_dir / "manifest.json").read_text(encoding="utf-8"))
    return {
        entry["path"]: entry["sha256"]
        for entry in manifest["files"]
        if prefix is None or entry["path"].startswith(prefix)
    }


def test_bitwise_reproduction(tmp_path):
    cfg = fast_scenario(**STOCHASTIC_SCENARIO)
    a = write_world(cfg, tmp_path / "a", 3)
    b = write_world(cfg, tmp_path / "b", 3)
    assert _checksums(a) == _checksums(b)
    # the manifest itself differs only by its creation timestamp
    assert sha256_file(a / "truth/arrival_time_min.npy") == sha256_file(
        b / "truth/arrival_time_min.npy"
    )


def test_stream_independence(tmp_path):
    """Observation-side seeds must not be able to move the fire."""
    cfg = fast_scenario(**STOCHASTIC_SCENARIO)
    base = write_world(cfg, tmp_path / "base", 0)
    base_truth = _checksums(base, "truth/")

    # Changing the *observation* configuration changes observations only.  The
    # files under truth/ that describe the world itself must be untouched.
    noisy = fast_scenario(
        **{
            **STOCHASTIC_SCENARIO,
            "observations": {
                "fire_sensors": [
                    {"sensor_id": "fire_sensor_a", "pixel_size_m": 480.0,
                     "cadence_min": 3.0, "p_detect_max": 0.2,
                     "geoloc_sigma_m": 900.0, "false_positive_rate_per_scan": 9.0}
                ],
                "missingness": {"mode": "correlated_outage", "p_fail": 0.6},
            },
        }
    )
    changed = write_world(noisy, tmp_path / "changed", 0)
    changed_truth = _checksums(changed, "truth/")

    world_files = (
        "truth/arrival_time_min.npy",
        "truth/burned_mask_final.npy",
        "truth/weather_true.csv",
        "truth/active_area_series.csv",
        "truth/ignitions.json",
        "truth/landscape/elevation_m.npy",
        "truth/landscape/fuel_multiplier.npy",
    )
    for name in world_files:
        assert base_truth[name] == changed_truth[name], f"{name} changed with the observer"

    assert (
        _checksums(base, "observations/") != _checksums(changed, "observations/")
    ), "the observation configuration must change the observations"


def test_nature_and_weather_seeds_do_change_the_truth(tmp_path):
    cfg = fast_scenario(**STOCHASTIC_SCENARIO)
    a = write_world(cfg, tmp_path / "a", 0)
    b = write_world(cfg, tmp_path / "b", 1)  # different world id -> all streams differ
    assert (
        _checksums(a)["truth/arrival_time_min.npy"]
        != _checksums(b)["truth/arrival_time_min.npy"]
    )
    assert (
        _checksums(a)["truth/weather_true.csv"] != _checksums(b)["truth/weather_true.csv"]
    )


def test_master_seed_changes_everything(tmp_path):
    cfg = fast_scenario(**STOCHASTIC_SCENARIO)
    other = cfg.replace(master_seed=cfg.master_seed + 1)
    a = write_world(cfg, tmp_path / "a", 0)
    b = write_world(other, tmp_path / "b", 0)
    assert (
        _checksums(a)["truth/arrival_time_min.npy"]
        != _checksums(b)["truth/arrival_time_min.npy"]
    )


def test_config_hash_is_recorded_and_matches(tmp_path):
    cfg = fast_scenario()
    world_dir = write_world(cfg, tmp_path / "w", 0)
    manifest = json.loads((world_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads(
        (world_dir / "metadata/world_metadata.json").read_text(encoding="utf-8")
    )
    assert manifest["config_hash"] == cfg.config_hash()
    assert metadata["config_hash"] == cfg.config_hash()


def test_in_memory_generation_is_repeatable():
    cfg = fast_scenario(**STOCHASTIC_SCENARIO)
    a, b = generate_world(cfg, 2), generate_world(cfg, 2)
    assert np.array_equal(
        np.nan_to_num(a.truth.arrival_time_min, posinf=-1.0),
        np.nan_to_num(b.truth.arrival_time_min, posinf=-1.0),
    )
    for name in ("fire_detections", "fire_scan_log", "weather_observations"):
        ta, tb = getattr(a.observations, name), getattr(b.observations, name)
        assert ta.names == tb.names
        for column in ta.names:
            assert np.array_equal(ta.columns[column], tb.columns[column])


def test_generation_is_not_order_dependent():
    """Generating other worlds in between must not perturb a world."""
    cfg = fast_scenario(**STOCHASTIC_SCENARIO)
    first = generate_world(cfg, 5)
    for other in range(3):
        generate_world(cfg, other)
    again = generate_world(cfg, 5)
    assert np.array_equal(
        np.nan_to_num(first.truth.arrival_time_min, posinf=-1.0),
        np.nan_to_num(again.truth.arrival_time_min, posinf=-1.0),
    )
    assert np.array_equal(
        first.observations.fire_detections.columns["x_m"],
        again.observations.fire_detections.columns["x_m"],
    )
