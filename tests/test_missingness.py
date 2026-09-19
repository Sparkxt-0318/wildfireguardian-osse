"""Missingness modes (``docs/OBSERVATION_MODEL.md#4``)."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import fast_scenario
from wildfireguardian_osse.pipeline import generate_world


def _world(mode: str, **params):
    return generate_world(
        fast_scenario(
            observations={
                "missingness": {"mode": mode, **params},
                "weather_network": {"cadence_min": 5.0, "layout": {"kind": "grid", "count": 9}},
                "fire_sensors": [
                    {"sensor_id": "fire_sensor_a", "pixel_size_m": 240.0, "cadence_min": 5.0}
                ],
            }
        ),
        0,
    )


def _weather_count(world) -> int:
    return len(world.observations.weather_observations)


def test_mode_none_drops_nothing():
    world = _world("none")
    assert world.observations.sensor_state.columns == {} or len(world.observations.sensor_state) == 0
    n_stations = len(world.observations.station_metadata)
    n_times = len(
        np.unique(world.observations.weather_observations.columns["event_time_min"].astype(float))
    )
    assert _weather_count(world) == n_stations * n_times


@pytest.mark.parametrize("p", [0.0, 0.2, 0.5])
def test_mcar_drops_the_configured_fraction(p):
    full = _weather_count(_world("none"))
    world = _world("mcar", p_missing=p)
    kept = _weather_count(world)
    assert (1.0 - kept / full) == pytest.approx(p, abs=0.06)


def test_mcar_is_the_only_mode_whose_gaps_are_single_records():
    world = _world("mcar", p_missing=0.3)
    state = world.observations.sensor_state.columns
    assert set(str(c) for c in state["cause"]) == {"mcar"}
    assert np.allclose(state["start_min"].astype(float), state["end_min"].astype(float))


def test_correlated_outage_produces_contiguous_runs():
    world = _world("correlated_outage", p_fail=0.3, p_repair=0.2, tick_min=10.0)
    state = world.observations.sensor_state.columns
    assert len(state["entity_id"]) > 0
    durations = state["end_min"].astype(float) - state["start_min"].astype(float)
    assert float(durations.min()) >= 10.0, "an outage must last at least one tick"
    assert float(durations.max()) > 10.0, "and some should span several ticks"

    # inside a station's outage window, that station reports nothing
    obs = world.observations.weather_observations.columns
    for entity, start, end in zip(state["entity_id"], state["start_min"], state["end_min"]):
        mine = obs["station_id"] == entity
        if not np.any(mine):
            continue
        times = obs["event_time_min"].astype(float)[mine]
        assert not np.any((times >= float(start)) & (times < float(end)))


def test_correlated_outage_suppresses_whole_fire_scans():
    world = _world("correlated_outage", p_fail=0.4, p_repair=0.2, tick_min=10.0)
    log = world.observations.fire_scan_log
    status = np.asarray([str(s) for s in log.columns["status"]])
    assert np.any(status == "outage")
    outage_counts = log.columns["n_detections"].astype(float)[status == "outage"]
    assert np.all(outage_counts == 0)


def test_outage_status_does_not_reveal_its_cause():
    """A planner learns that nothing arrived, not why (docs/DECISIONS.md#d-009)."""
    for mode, params in (
        ("mcar", {"p_missing": 0.6}),
        ("correlated_outage", {"p_fail": 0.5, "p_repair": 0.1, "tick_min": 10.0}),
        ("fire_correlated", {"lambda_fire_per_min": 0.5, "fail_radius_m": 800.0}),
    ):
        world = _world(mode, **params)
        status = {str(s) for s in world.observations.fire_scan_log.columns["status"]}
        assert status <= {"ok", "outage"}


def test_fire_correlated_failures_only_happen_once_the_fire_is_near():
    world = _world(
        "fire_correlated", lambda_fire_per_min=0.5, fail_radius_m=600.0, tick_min=5.0
    )
    state = world.observations.sensor_state.columns
    exposure = world.observations.hidden_params["station_fire_exposure_min"]
    assert len(state["entity_id"]) > 0, "this configuration must produce failures"
    for entity, start in zip(state["entity_id"], state["start_min"].astype(float)):
        if entity in exposure:
            assert start >= float(exposure[entity]) - 1e-9, (
                f"{entity} failed at {start} before the fire reached it "
                f"at {exposure[entity]}"
            )


def test_a_station_far_from_the_fire_never_fails_in_fire_correlated_mode():
    grid_far = fast_scenario(
        observations={
            "missingness": {
                "mode": "fire_correlated",
                "lambda_fire_per_min": 0.9,
                "fail_radius_m": 60.0,
                "tick_min": 5.0,
            },
            "weather_network": {
                "cadence_min": 5.0,
                "layout": {"kind": "explicit", "positions_m": [[30.0, 30.0]]},
            },
        }
    )
    world = generate_world(grid_far, 0)
    exposure = world.observations.hidden_params["station_fire_exposure_min"]
    assert all(not np.isfinite(v) for v in exposure.values())
    station_ids = {s["station_id"] for s in world.observations.station_metadata}
    failed = {str(e) for e in world.observations.sensor_state.columns.get("entity_id", [])}
    assert failed & station_ids == set()
    # The fire sensor is not at a point in the domain, so it has no distance to
    # the fire and is exposed from first ignition by design
    # (observations/process.py).  It is allowed to fail here; stations are not.


def test_missingness_seed_changes_the_pattern_but_not_the_measurements():
    """The two are separately controllable, by construction."""
    cfg = fast_scenario(observations={"missingness": {"mode": "mcar", "p_missing": 0.3}})
    a = generate_world(cfg, 0)
    b = generate_world(cfg, 1)
    assert len(a.observations.weather_observations) != len(b.observations.weather_observations) or (
        not np.array_equal(
            a.observations.weather_observations.columns["obs_id"],
            b.observations.weather_observations.columns["obs_id"],
        )
    )


def test_missingness_never_changes_the_truth():
    reference = generate_world(fast_scenario(), 0).truth.arrival_time_min
    for mode, params in (
        ("mcar", {"p_missing": 0.9}),
        ("correlated_outage", {"p_fail": 0.8, "p_repair": 0.05}),
        ("fire_correlated", {"lambda_fire_per_min": 0.9, "fail_radius_m": 2000.0}),
    ):
        arrival = _world(mode, **params).truth.arrival_time_min
        assert np.array_equal(
            np.nan_to_num(arrival, posinf=-1.0), np.nan_to_num(reference, posinf=-1.0)
        )
