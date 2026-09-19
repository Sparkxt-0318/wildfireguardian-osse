"""Prefix causality: no observation may depend on the future.

Simulate the same world to ``H1`` and to ``H2 > H1``.  Every observation whose
``availability_time_min`` is at or before ``H1`` must be **bit-identical**
between the two runs.  If any observation were computed from the world after
its own event time -- or if any random stream were shared in a way that made
the length of the run matter -- this would fail
(``docs/TIME_SEMANTICS.md#6``, ``docs/FAILURE_MODES.md#L-02``).
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import fast_scenario, validation_scenario
from wildfireguardian_osse.pipeline import generate_world

STREAMS = ("fire_detections", "fire_scan_log", "weather_observations")

HARD_SCENARIO = dict(
    weather={"wind_speed_ms": 4.0, "speed_sigma_ms": 1.2, "dir_sigma_deg": 25.0},
    nature={
        "spotting": {"enabled": True, "interval_min": 10.0,
                     "rate_per_ha_per_min": 0.02, "median_distance_m": 300.0,
                     "p_ignite": 0.6}
    },
    observations={
        "fire_sensors": [
            {"sensor_id": "fire_sensor_a", "pixel_size_m": 240.0, "cadence_min": 7.0,
             "false_positive_rate_per_scan": 1.5,
             "latency": {"processing_latency_min": 4.0, "delivery_latency_min": 2.0,
                         "jitter_mean_min": 1.5}}
        ],
        "weather_network": {"cadence_min": 5.0, "layout": {"kind": "grid", "count": 9}},
        "missingness": {"mode": "correlated_outage", "p_fail": 0.25,
                        "p_repair": 0.3, "tick_min": 10.0},
    },
)


def _prefix(world, horizon: float, stream: str):
    table = getattr(world.observations, stream)
    if len(table) == 0:
        return table
    mask = table.columns["availability_time_min"].astype(float) <= horizon
    return table.select(mask)


def _assert_identical(short, long, horizon: float) -> int:
    total = 0
    for stream in STREAMS:
        a = _prefix(short, horizon, stream)
        b = _prefix(long, horizon, stream)
        assert a.names == b.names, stream
        assert len(a) == len(b), f"{stream}: {len(a)} vs {len(b)} records available by {horizon}"
        for column in a.names:
            assert np.array_equal(a.columns[column], b.columns[column]), f"{stream}.{column}"
        total += len(a)
    return total


@pytest.mark.parametrize("h1, h2", [(45.0, 90.0), (60.0, 180.0), (30.0, 300.0)])
def test_observations_available_by_h1_do_not_change_when_the_run_is_extended(h1, h2):
    short = generate_world(fast_scenario(**HARD_SCENARIO, time={"horizon_min": h1, "dt_min": 1.0}), 0)
    long = generate_world(fast_scenario(**HARD_SCENARIO, time={"horizon_min": h2, "dt_min": 1.0}), 0)
    n = _assert_identical(short, long, h1)
    assert n > 20, "the comparison must not be vacuous"


def test_the_truth_prefix_is_also_stable():
    """The fire up to H1 is the same fire, however long the run continues."""
    short = generate_world(fast_scenario(**HARD_SCENARIO, time={"horizon_min": 45.0, "dt_min": 1.0}), 0)
    long = generate_world(fast_scenario(**HARD_SCENARIO, time={"horizon_min": 180.0, "dt_min": 1.0}), 0)
    a, b = short.truth.arrival_time_min, long.truth.arrival_time_min
    burned_early = np.isfinite(a)
    assert np.count_nonzero(burned_early) > 50
    assert np.array_equal(a[burned_early], b[burned_early])

    early_spots = [e.to_dict() for e in short.truth.spot_events]
    later_spots = [e.to_dict() for e in long.truth.spot_events][: len(early_spots)]
    assert early_spots == later_spots


def test_prefix_causality_holds_under_fire_correlated_missingness():
    """The mode whose absences depend on the hidden fire is the risky one."""
    scenario = {
        **HARD_SCENARIO,
        "observations": {
            **HARD_SCENARIO["observations"],
            "missingness": {"mode": "fire_correlated", "lambda_fire_per_min": 0.3,
                            "fail_radius_m": 700.0, "tick_min": 5.0},
        },
    }
    short = generate_world(fast_scenario(**scenario, time={"horizon_min": 45.0, "dt_min": 1.0}), 0)
    long = generate_world(fast_scenario(**scenario, time={"horizon_min": 180.0, "dt_min": 1.0}), 0)
    assert _assert_identical(short, long, 45.0) > 20


def test_prefix_causality_holds_for_a_validation_world():
    short = validation_scenario("v2_uniform_constant_wind", time={"horizon_min": 60.0, "dt_min": 1.0})
    long = validation_scenario("v2_uniform_constant_wind", time={"horizon_min": 180.0, "dt_min": 1.0})
    assert _assert_identical(generate_world(short, 1), generate_world(long, 1), 60.0) > 20


def test_a_detection_is_never_generated_from_a_later_state():
    """Every real detection's pixel was alight at the reported event time."""
    world = generate_world(fast_scenario(**HARD_SCENARIO), 0)
    from wildfireguardian_osse.observations.fire import _pixel_index_map

    ledger = world.observations.detection_ledger.columns
    grid = world.truth.grid
    index, n_px, _ = _pixel_index_map(grid, 240.0)
    flat = index.reshape(-1)
    residence = world.config.nature.residence_time_min
    checked = 0
    for obs_id, kind, t, x, y in zip(
        ledger["obs_id"], ledger["kind"], ledger["event_time_min"].astype(float),
        ledger["true_x_m"].astype(float), ledger["true_y_m"].astype(float),
    ):
        if str(kind) != "true_detection":
            continue
        pixel = int(y // 240.0) * n_px + int(x // 240.0)
        active = world.truth.active_mask(float(t), residence).reshape(-1)
        assert np.any(active & (flat == pixel)), f"{obs_id} saw a pixel that was not alight"
        checked += 1
    assert checked > 10
