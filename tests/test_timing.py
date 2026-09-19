"""Observation time semantics (``docs/TIME_SEMANTICS.md``)."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import fast_scenario
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.storage.reader import available_at, load_world
from wildfireguardian_osse.timeline import (
    TIME_COLUMNS,
    ObservationTimes,
    build_time_arrays,
    parse_epoch,
    snap_to_step,
    to_utc,
)
from wildfireguardian_osse.validation.checks import check_time_semantics

STREAMS = ("fire_detections", "fire_scan_log", "weather_observations")


def test_ordering_is_enforced_at_construction():
    ObservationTimes(0.0, 0.0, 0.0, 0.0)
    ObservationTimes(1.0, 2.0, 3.0, 4.0)
    with pytest.raises(ValueError, match="ordering violated"):
        ObservationTimes(5.0, 4.0, 3.0, 2.0)
    with pytest.raises(ValueError, match="ordering violated"):
        ObservationTimes(0.0, 1.0, 5.0, 4.0)


def test_negative_latency_components_are_rejected():
    with pytest.raises(ValueError, match="must be >= 0"):
        build_time_arrays(
            np.array([0.0]),
            acquisition_offset_min=0.0,
            processing_latency_min=-1.0,
            delivery_latency_min=0.0,
        )
    with pytest.raises(ValueError, match="jitter must be non-negative"):
        build_time_arrays(
            np.array([0.0]),
            acquisition_offset_min=0.0,
            processing_latency_min=1.0,
            delivery_latency_min=0.0,
            jitter_min=np.array([-0.5]),
        )


def test_build_time_arrays_composes_the_budget():
    times = build_time_arrays(
        np.array([0.0, 10.0]),
        acquisition_offset_min=0.5,
        processing_latency_min=2.0,
        delivery_latency_min=1.0,
        jitter_min=np.array([0.0, 3.0]),
    )
    assert list(times) == list(TIME_COLUMNS)
    assert times["availability_time_min"].tolist() == [3.5, 16.5]
    assert ObservationTimes(*[times[c][1] for c in TIME_COLUMNS]).total_latency_min == 6.5


def test_every_stream_satisfies_the_ordering_invariant(fast_world):
    for name in STREAMS:
        table = getattr(fast_world.observations, name)
        assert len(table) > 0, f"{name} is empty; the test would be vacuous"
        assert check_time_semantics(table.columns, name) == []


def test_availability_never_precedes_the_event(fast_world):
    for name in STREAMS:
        columns = getattr(fast_world.observations, name).columns
        latency = (
            columns["availability_time_min"].astype(float)
            - columns["event_time_min"].astype(float)
        )
        assert float(latency.min()) >= 0.0
        assert float(latency.min()) > 0.0, "this configuration has a positive latency"


def test_reported_event_time_is_the_snapped_simulation_time(fast_world):
    dt = fast_world.config.time.dt_min
    for name in STREAMS:
        events = getattr(fast_world.observations, name).columns["event_time_min"].astype(float)
        assert np.allclose(events / dt, np.round(events / dt))


def test_available_at_is_monotone_and_never_early(written_world):
    world = load_world(written_world)
    table = world.fire_detections
    horizon = float(world.metadata["horizon_min"])
    counts = []
    for t in np.linspace(0.0, horizon * 2, 25):
        subset = available_at(table, t)
        assert np.all(subset["availability_time_min"] <= t + 1e-9)
        counts.append(len(subset["obs_id"]))
    assert counts == sorted(counts)
    assert counts[-1] == len(table["obs_id"])


def test_available_at_rejects_a_table_without_the_column():
    with pytest.raises(KeyError, match="availability_time_min"):
        available_at({"event_time_min": np.array([1.0])}, 10.0)


def test_filtering_on_event_time_would_be_optimistic(written_world):
    """The bug docs/FAILURE_MODES.md#L-03 warns about, made visible."""
    world = load_world(written_world)
    table = world.fire_detections
    # Evaluated at the last scan's event time: every detection now exists in
    # the world, but the newest ones have not been delivered yet.  Between
    # scans the two filters happen to agree, which is exactly why the mistake
    # survives casual testing.
    t = float(table["event_time_min"].astype(float).max())
    legal = len(available_at(table, t)["obs_id"])
    by_event = int(np.count_nonzero(table["event_time_min"].astype(float) <= t))
    assert by_event == len(table["obs_id"])
    assert by_event > legal, "latency must make event-time filtering strictly optimistic"


def test_utc_columns_match_the_epoch(fast_world):
    epoch = parse_epoch(fast_world.config.epoch)
    columns = fast_world.observations.fire_detections.columns
    for k in range(min(5, len(columns["event_time_min"]))):
        assert columns["event_time_utc"][k] == to_utc(epoch, float(columns["event_time_min"][k]))


def test_snap_to_step_is_clamped_to_the_window():
    assert snap_to_step(7.3, 1.0, 100.0) == 7.0
    assert snap_to_step(7.6, 1.0, 100.0) == 8.0
    assert snap_to_step(-5.0, 1.0, 100.0) == 0.0
    assert snap_to_step(500.0, 1.0, 100.0) == 100.0


def test_records_may_become_available_after_the_horizon(fast_world):
    """Kept, not dropped: a consumer at t <= horizon correctly cannot use them."""
    horizon = fast_world.config.time.horizon_min
    columns = fast_world.observations.fire_detections.columns
    events = columns["event_time_min"].astype(float)
    availability = columns["availability_time_min"].astype(float)
    assert np.all(events <= horizon + 1e-9)
    assert np.any(availability > events)
