"""Red-team: attempts to recover hidden truth from planner-facing files.

A clean pass does not prove leakage is impossible -- only that these attacks
found none (``docs/OBSERVATION_MODEL.md#6``).
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

from conftest import fast_scenario, validation_scenario, write_world
from wildfireguardian_osse.storage.manifest import (
    HIDDEN,
    PLANNER_VISIBLE,
    STATIC_CONTEXT_ALLOWLIST,
)
from wildfireguardian_osse.storage.tables import Table
from wildfireguardian_osse.validation.checks import validate_world
from wildfireguardian_osse.validation.leakage import scan_world_for_leakage

LEAKY_SCENARIO = dict(
    nature={
        "spotting": {"enabled": True, "interval_min": 10.0,
                     "rate_per_ha_per_min": 0.02, "median_distance_m": 300.0,
                     "p_ignite": 0.6}
    },
    observations={
        "fire_sensors": [
            {"sensor_id": "fire_sensor_a", "pixel_size_m": 240.0,
             "cadence_min": 10.0, "false_positive_rate_per_scan": 1.5}
        ],
        "missingness": {"mode": "fire_correlated", "lambda_fire_per_min": 0.3,
                        "fail_radius_m": 600.0},
    },
)


@pytest.fixture()
def world(tmp_path):
    return write_world(fast_scenario(**LEAKY_SCENARIO), tmp_path / "batch", 0)


# -- the clean case ---------------------------------------------------------

def test_a_generated_world_has_no_leakage(world):
    assert scan_world_for_leakage(world) == []
    assert validate_world(world) == []


def test_every_validation_world_is_clean(tmp_path):
    for k, name in enumerate(("v4_fuel_discontinuity", "v7_spotting_on", "v8_sensor_outage")):
        path = write_world(validation_scenario(name), tmp_path / "v", k)
        assert validate_world(path) == [], name


# -- visibility labelling ---------------------------------------------------

def test_every_file_is_labelled_and_labels_match_the_layout(world):
    manifest = json.loads((world / "manifest.json").read_text(encoding="utf-8"))
    listed = {e["path"]: e["visibility"] for e in manifest["files"]}
    on_disk = {
        p.relative_to(world).as_posix()
        for p in world.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert set(listed) == on_disk
    for path, visibility in listed.items():
        if path.startswith("truth/"):
            assert visibility == HIDDEN
        else:
            assert visibility == PLANNER_VISIBLE


def test_the_manifest_is_a_pure_inventory(world):
    """No aggregate truth and no seed in manifest.json (docs/OBSERVATION_MODEL.md#5)."""
    text = (world / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert "summary" not in manifest
    assert "burned_area_ha" not in text
    seeds = json.loads((world / "truth/nature_params.json").read_text(encoding="utf-8"))["seeds"]
    for value in seeds["derived_stream_seeds"].values():
        assert str(value) not in text


# -- no truth raster is reachable -------------------------------------------

def test_no_planner_visible_raster_reproduces_the_fire(world):
    arrival = np.load(world / "truth/arrival_time_min.npy")
    burned = np.load(world / "truth/burned_mask_final.npy")
    for path in (world / "observations").rglob("*.npy"):
        candidate = np.load(path)
        assert not np.array_equal(candidate, burned)
        assert not np.array_equal(
            np.nan_to_num(candidate.astype(float), posinf=0.0),
            np.nan_to_num(arrival.astype(float), posinf=0.0),
        )


def test_static_context_is_exactly_the_allowlist(world):
    present = {
        p.relative_to(world).as_posix() for p in (world / "observations/static_context").iterdir()
    }
    assert present == set(STATIC_CONTEXT_ALLOWLIST)


def test_published_fuel_class_is_a_coarsening_not_the_multiplier(world):
    published = np.load(world / "observations/static_context/fuel_class.npy")
    hidden = np.load(world / "truth/landscape/fuel_multiplier.npy")
    assert np.issubdtype(published.dtype, np.integer)
    assert np.unique(published).size <= np.unique(hidden).size


# -- the scanner actually catches things ------------------------------------

def _corrupt(world, tmp_path, name):
    target = tmp_path / name
    shutil.copytree(world, target)
    return target


def test_scanner_catches_a_leaked_truth_raster(world, tmp_path):
    target = _corrupt(world, tmp_path, "leaked_raster")
    shutil.copy(
        target / "truth/arrival_time_min.npy",
        target / "observations/static_context/elevation_m.npy",
    )
    findings = scan_world_for_leakage(target)
    assert any("bit-identical" in f for f in findings)


def test_scanner_catches_a_leaked_field_name(world, tmp_path):
    target = _corrupt(world, tmp_path, "leaked_field")
    table = Table.from_columns(
        {"obs_id": ["a"], "availability_time_min": [1.0], "true_arrival_time_min": [5.0]}
    )
    table.to_csv(target / "observations/fire_detections.csv")
    findings = scan_world_for_leakage(target)
    assert any("forbidden fragment" in f for f in findings)


def test_scanner_catches_a_leaked_seed(world, tmp_path):
    target = _corrupt(world, tmp_path, "leaked_seed")
    seeds = json.loads((target / "truth/nature_params.json").read_text())["seeds"]
    secret = seeds["derived_stream_seeds"]["nature_seed"]
    payload = json.loads((target / "observations/station_metadata.json").read_text())
    payload["calibration_reference"] = secret
    (target / "observations/station_metadata.json").write_text(json.dumps(payload))
    findings = scan_world_for_leakage(target)
    assert any("seed value" in f for f in findings)


def test_scanner_catches_a_real_instrument_name(world, tmp_path):
    target = _corrupt(world, tmp_path, "instrument")
    specs = json.loads((target / "observations/sensor_specs_published.json").read_text())
    specs["fire_sensors"][0]["sensor_id"] = "viirs_like_sensor"
    (target / "observations/sensor_specs_published.json").write_text(json.dumps(specs))
    findings = scan_world_for_leakage(target)
    assert any("real instrument" in f for f in findings)


def test_scanner_catches_a_swept_value_in_a_planner_visible_identifier(world, tmp_path):
    target = _corrupt(world, tmp_path, "identifier")
    metadata = json.loads((target / "metadata/world_metadata.json").read_text())
    summary = json.loads((target / "truth/world_summary.json").read_text())
    metadata["scenario_name"] = f"run_wind_{summary['sweep_axes']['wind_speed_ms']}"
    (target / "metadata/world_metadata.json").write_text(json.dumps(metadata))
    findings = scan_world_for_leakage(target)
    assert any("swept hidden value" in f for f in findings)


def test_scanner_catches_an_unlisted_planner_visible_raster(world, tmp_path):
    target = _corrupt(world, tmp_path, "extra_raster")
    np.save(target / "observations/static_context/secret.npy", np.zeros((4, 4)))
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["files"].append(
        {"path": "observations/static_context/secret.npy", "visibility": PLANNER_VISIBLE,
         "description": "x", "bytes": 0, "sha256": "0" * 64}
    )
    (target / "manifest.json").write_text(json.dumps(manifest))
    findings = scan_world_for_leakage(target)
    assert any("outside the static-context allow-list" in f for f in findings)


def test_validate_detects_a_tampered_file(world, tmp_path):
    target = _corrupt(world, tmp_path, "tampered")
    path = target / "observations/fire_detections.csv"
    path.write_text(path.read_text() + "\n")
    problems = validate_world(target)
    assert any("checksum mismatch" in p for p in problems)


# -- the weather stream carries no true wind --------------------------------

def test_planner_weather_is_never_the_true_series(world):
    from wildfireguardian_osse.storage.tables import read_table

    observed = read_table(world / "observations/weather_station_obs.csv")
    truth = read_table(world / "truth/weather_true.csv")
    assert not set(np.round(observed["wind_speed_ms"], 9)) <= set(
        np.round(truth["wind_speed_ms"], 9)
    )
    assert "wind_speed_ms" in observed and "t_min" not in observed
