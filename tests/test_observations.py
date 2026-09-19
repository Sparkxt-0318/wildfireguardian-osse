"""The fire and weather observation operators (``docs/OBSERVATION_MODEL.md``)."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import fast_scenario
from wildfireguardian_osse.observations.fire import _pixel_index_map
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.sensors.specs import (
    hidden_fire_sensor_params,
    looks_like_real_instrument,
    published_fire_sensor_spec,
)


def _sensor(**overrides):
    base = {
        "sensor_id": "fire_sensor_a",
        "pixel_size_m": 240.0,
        "cadence_min": 10.0,
        "p_detect_max": 0.9,
        "detect_ref_area_m2": 8000.0,
        "geoloc_sigma_m": 90.0,
        "false_positive_rate_per_scan": 0.0,
    }
    base.update(overrides)
    return fast_scenario(observations={"fire_sensors": [base]})


# -- detection --------------------------------------------------------------

def test_detection_count_increases_with_p_detect_max():
    counts = [
        generate_world(_sensor(p_detect_max=p), 0).observations.n_detections()
        for p in (0.0, 0.3, 0.6, 1.0)
    ]
    assert counts[0] == 0
    assert counts == sorted(counts)
    assert counts[-1] > counts[1]


def test_detection_count_decreases_as_the_reference_area_grows():
    counts = [
        generate_world(_sensor(detect_ref_area_m2=a), 0).observations.n_detections()
        for a in (2000.0, 20000.0, 200000.0)
    ]
    assert counts == sorted(counts, reverse=True)


def test_a_perfect_sensor_reports_every_burning_pixel():
    world = generate_world(_sensor(p_detect_max=1.0, detect_ref_area_m2=1.0), 0)
    ledger = world.observations.detection_ledger.columns
    scans = world.observations.fire_scan_log
    truth = world.truth
    index, n_px, n_py = _pixel_index_map(truth.grid, 240.0)
    residence = world.config.nature.residence_time_min
    for t in scans.columns["event_time_min"].astype(float):
        active = truth.active_mask(float(t), residence).reshape(-1)
        expected = np.unique(index.reshape(-1)[active]).size
        got = int(np.count_nonzero(ledger["event_time_min"].astype(float) == t))
        assert got == expected


def test_only_actively_burning_pixels_are_ever_reported(fast_world):
    """No detection may come from a pixel that is merely *already burned*."""
    ledger = fast_world.observations.detection_ledger.columns
    kinds = np.asarray([str(k) for k in ledger["kind"]])
    areas = ledger["pixel_active_area_m2"].astype(float)
    assert np.all(areas[kinds == "true_detection"] > 0.0)


# -- geolocation noise ------------------------------------------------------

def test_geolocation_error_matches_the_configured_sigma():
    sigma = 200.0
    world = generate_world(_sensor(geoloc_sigma_m=sigma, p_detect_max=1.0), 0)
    ledger = world.observations.detection_ledger.columns
    real = np.asarray([str(k) == "true_detection" for k in ledger["kind"]])
    dx = ledger["reported_x_m"].astype(float)[real] - ledger["true_x_m"].astype(float)[real]
    dy = ledger["reported_y_m"].astype(float)[real] - ledger["true_y_m"].astype(float)[real]
    error = np.concatenate([dx, dy])
    assert error.size > 60
    assert abs(float(error.mean())) < sigma * 0.35
    assert float(error.std()) == pytest.approx(sigma, rel=0.35)


def test_zero_geolocation_sigma_reports_exact_pixel_centres():
    world = generate_world(_sensor(geoloc_sigma_m=0.0, p_detect_max=1.0), 0)
    ledger = world.observations.detection_ledger.columns
    real = np.asarray([str(k) == "true_detection" for k in ledger["kind"]])
    assert np.allclose(
        ledger["reported_x_m"].astype(float)[real], ledger["true_x_m"].astype(float)[real]
    )


# -- false positives --------------------------------------------------------

def test_false_positive_count_tracks_the_poisson_rate():
    rate = 3.0
    world = generate_world(_sensor(false_positive_rate_per_scan=rate), 0)
    ledger = world.observations.detection_ledger.columns
    n_fp = int(np.count_nonzero(np.asarray([str(k) for k in ledger["kind"]]) == "false_positive"))
    n_scans = len(world.observations.fire_scan_log)
    assert n_scans > 5
    assert n_fp / n_scans == pytest.approx(rate, rel=0.5)


def test_false_positives_are_unlabelled_in_the_planner_file():
    """docs/DECISIONS.md#d-007: the planner must not be able to filter them."""
    world = generate_world(_sensor(false_positive_rate_per_scan=3.0), 0)
    detections = world.observations.fire_detections
    ledger = world.observations.detection_ledger.columns
    fp_ids = {
        str(i)
        for i, k in zip(ledger["obs_id"], ledger["kind"])
        if str(k) == "false_positive"
    }
    assert fp_ids, "this test needs at least one false positive"
    assert fp_ids <= set(str(i) for i in detections.columns["obs_id"])
    for name in detections.names:
        assert "false" not in name.lower() and "kind" not in name.lower()
    # and nothing in a planner-visible row distinguishes them
    assert set(detections.names) == {
        "obs_id", "sensor_id", "scan_id",
        "event_time_min", "acquisition_time_min",
        "processing_time_min", "availability_time_min",
        "x_m", "y_m", "pixel_size_m", "geoloc_sigma_m", "confidence",
        "event_time_utc", "availability_time_utc",
    }


def test_zero_false_positive_rate_produces_none():
    world = generate_world(_sensor(false_positive_rate_per_scan=0.0), 0)
    kinds = {str(k) for k in world.observations.detection_ledger.columns["kind"]}
    assert "false_positive" not in kinds


# -- scan log ---------------------------------------------------------------

def test_every_scan_is_logged_even_when_empty():
    world = generate_world(
        _sensor(cadence_min=5.0, p_detect_max=0.0, false_positive_rate_per_scan=0.0), 0
    )
    log = world.observations.fire_scan_log
    horizon = world.config.time.horizon_min
    expected = int(np.floor((horizon - 5.0) / 5.0)) + 1
    assert len(log) == expected
    assert set(int(n) for n in log.columns["n_detections"]) == {0}
    assert world.observations.n_detections() == 0


def test_scan_log_counts_match_the_detections(fast_world):
    log = fast_world.observations.fire_scan_log
    detections = fast_world.observations.fire_detections
    for scan_id, n in zip(log.columns["scan_id"], log.columns["n_detections"]):
        actual = int(np.count_nonzero(detections.columns["scan_id"] == scan_id))
        assert actual == int(n)


# -- cadence and latency ----------------------------------------------------

def test_cadence_controls_the_number_of_scans():
    counts = [
        len(generate_world(_sensor(cadence_min=c), 0).observations.fire_scan_log)
        for c in (5.0, 10.0, 30.0)
    ]
    assert counts == sorted(counts, reverse=True)


def test_latency_shifts_availability_without_touching_the_event():
    slow = fast_scenario(
        observations={
            "fire_sensors": [
                {"sensor_id": "fire_sensor_a", "pixel_size_m": 240.0,
                 "latency": {"processing_latency_min": 30.0, "delivery_latency_min": 10.0,
                             "jitter_mean_min": 0.0}}
            ]
        }
    )
    quick = fast_scenario(
        observations={
            "fire_sensors": [
                {"sensor_id": "fire_sensor_a", "pixel_size_m": 240.0,
                 "latency": {"processing_latency_min": 1.0, "delivery_latency_min": 0.0,
                             "jitter_mean_min": 0.0}}
            ]
        }
    )
    a = generate_world(slow, 0).observations.fire_detections.columns
    b = generate_world(quick, 0).observations.fire_detections.columns
    assert np.array_equal(a["event_time_min"], b["event_time_min"])
    assert np.array_equal(a["x_m"], b["x_m"]), "latency must not change what is seen"
    assert np.all(a["availability_time_min"].astype(float)
                  - b["availability_time_min"].astype(float) == pytest.approx(39.0))


# -- weather stream ---------------------------------------------------------

def test_weather_measurement_error_matches_the_configured_sigma():
    cfg = fast_scenario(
        observations={"weather_network": {"sigma_speed_ms": 2.0, "cadence_min": 5.0,
                                          "layout": {"kind": "grid", "count": 9}}}
    )
    world = generate_world(cfg, 0)
    obs = world.observations.weather_observations.columns
    truth = world.truth.weather.sample_arrays(obs["event_time_min"].astype(float))
    error = obs["wind_speed_ms"].astype(float) - truth["wind_speed_ms"]
    assert error.size > 100
    assert abs(float(error.mean())) < 0.5
    assert float(error.std()) == pytest.approx(2.0, rel=0.25)


def test_station_positions_are_inside_the_domain(fast_world):
    grid = fast_world.truth.grid
    for station in fast_world.observations.station_metadata:
        assert 0.0 <= station["x_m"] <= grid.width_m
        assert 0.0 <= station["y_m"] <= grid.height_m


def test_random_station_layout_is_seeded_and_reproducible():
    cfg = fast_scenario(
        observations={"weather_network": {"layout": {"kind": "random", "count": 6}}}
    )
    a = generate_world(cfg, 0).observations.station_metadata
    b = generate_world(cfg, 0).observations.station_metadata
    c = generate_world(cfg, 1).observations.station_metadata
    assert a == b
    assert a != c


# -- published vs hidden specification --------------------------------------

def test_published_spec_omits_the_generative_parameters():
    cfg = fast_scenario()
    sensor = cfg.observations.fire_sensors[0]
    published = published_fire_sensor_spec(sensor)
    hidden = hidden_fire_sensor_params(sensor)
    for secret in ("p_detect_max", "detect_ref_area_m2", "false_positive_rate_per_scan"):
        assert secret not in published
        assert secret in hidden
    assert published["nominal_geoloc_sigma_m"] == sensor.geoloc_sigma_m


def test_generic_sensor_ids_pass_the_instrument_tripwire(fast_world):
    for spec in fast_world.observations.published_specs["fire_sensors"]:
        assert looks_like_real_instrument(spec["sensor_id"]) is None
    assert looks_like_real_instrument("viirs_like_sensor") == "viirs"
    assert looks_like_real_instrument("GK-2A") == "gk2a"
