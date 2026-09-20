"""The leakage boundary: what a planner can and cannot reach.

These are the runtime assertions PROTOCOL.md section 12 requires.  They are
written as attacks, in the spirit of ``AGENTS.md`` Agent C: each one tries to
get hidden truth into a planner-facing object and fails.
"""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_fv.info import (
    InformationSet,
    LeakageError,
    audit_information_set,
    build_information_set,
    truth_access_guard,
)
from wildfireguardian_fv.world import ExperimentWorld
from wildfireguardian_osse.nature.world import NatureTruth


def _reachable_objects(root, max_nodes: int = 200_000):
    """Every object reachable from ``root`` by attribute or container walk."""
    seen: set[int] = set()
    stack = [root]
    while stack and len(seen) < max_nodes:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        if isinstance(node, (str, bytes, int, float, bool, type(None), np.ndarray)):
            continue
        if isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
            continue
        if isinstance(node, (list, tuple, set, frozenset)):
            stack.extend(node)
            continue
        slots = getattr(node, "__dict__", None)
        if isinstance(slots, dict):
            stack.extend(slots.values())


def test_information_set_cannot_reach_hidden_truth(dev_world):
    info = build_information_set(dev_world, 60.0)
    forbidden = (NatureTruth, ExperimentWorld)
    for obj in _reachable_objects(info):
        assert not isinstance(obj, forbidden), (
            f"{type(obj).__name__} is reachable from an InformationSet; the "
            "planner has a path to hidden truth"
        )


def test_no_observation_is_available_after_s(dev_world):
    for s in (0.0, 17.0, 45.0, 120.0):
        info = build_information_set(dev_world, s)
        for name in ("fire_detections", "fire_scan_log", "weather_observations"):
            col = getattr(info, name)["availability_time_min"]
            if len(col):
                assert float(np.max(col.astype(float))) <= s + 1e-9


def test_a_late_processed_record_is_withheld_until_availability(dev_world):
    """A record whose event is in the past is still unusable until delivered."""
    det = dev_world.observations.fire_detections.columns
    if len(det.get("event_time_min", [])) == 0:
        pytest.skip("world produced no detections")
        return
    event = det["event_time_min"].astype(float)
    avail = det["availability_time_min"].astype(float)
    gap = avail - event
    assert float(np.max(gap)) > 0.0, "this world has no latency to test"
    s = float(np.min(event)) + 0.5 * float(np.min(gap[gap > 0]))
    info = build_information_set(dev_world, s)
    assert info.n_detections() == 0, (
        "a detection whose event time has passed but which has not been "
        "delivered must not be in D_s"
    )


def test_no_seed_value_is_planner_visible(dev_world):
    info = build_information_set(dev_world, 90.0)
    problems = audit_information_set(info, dev_world.all_hidden_seed_values())
    assert problems == []


def test_audit_catches_an_injected_forbidden_field(dev_world):
    info = build_information_set(dev_world, 60.0)
    poisoned = InformationSet(
        world_id=info.world_id,
        information_time_min=info.information_time_min,
        fire_detections=info.fire_detections,
        fire_scan_log=info.fire_scan_log,
        weather_observations=info.weather_observations,
        station_metadata=info.station_metadata,
        published_specs={**info.published_specs, "nature_params": {"r0": 3.0}},
        static_context=info.static_context,
        village=info.village,
        grid_meta=info.grid_meta,
        horizon_min=info.horizon_min,
    )
    assert any("nature_param" in p for p in audit_information_set(poisoned))


def test_audit_catches_an_injected_seed_value(dev_world):
    info = build_information_set(dev_world, 60.0)
    seed = dev_world.all_hidden_seed_values()[0]
    poisoned = InformationSet(
        world_id=info.world_id,
        information_time_min=info.information_time_min,
        fire_detections=info.fire_detections,
        fire_scan_log=info.fire_scan_log,
        weather_observations=info.weather_observations,
        station_metadata=info.station_metadata,
        published_specs=info.published_specs,
        static_context=info.static_context,
        village={**info.village, "village_id": f"v{seed}"},
        grid_meta=info.grid_meta,
        horizon_min=info.horizon_min,
    )
    assert any("seed value" in p for p in audit_information_set(poisoned, [seed]))


def test_build_refuses_a_negative_information_time(dev_world):
    with pytest.raises(ValueError):
        build_information_set(dev_world, -1.0)


def test_truth_access_guard_blocks_reading_a_truth_artefact(tmp_path):
    truth_dir = tmp_path / "truth"
    truth_dir.mkdir()
    np.save(truth_dir / "arrival_time_min.npy", np.zeros((2, 2)))
    assert np.load(truth_dir / "arrival_time_min.npy").shape == (2, 2)
    with truth_access_guard():
        with pytest.raises(LeakageError):
            np.load(truth_dir / "arrival_time_min.npy")
        with pytest.raises(LeakageError):
            open(truth_dir / "arrival_time_min.npy", "rb")
    assert np.load(truth_dir / "arrival_time_min.npy").shape == (2, 2)


def test_information_set_is_prefix_causal_in_the_horizon(gen_config):
    """Extending the simulated horizon must not change D_s for s <= H.

    The laboratory proves this for its own observation streams
    (``tests/test_causality_prefix.py``).  What is checked here is that the
    experiment's gate preserves it: a longer world must hand the planner the
    same information set at the same ``s``.
    """
    from dataclasses import replace

    from wildfireguardian_fv.worlds import build_experiment_world

    short = build_experiment_world(gen_config, "open_plain", 5)
    long = build_experiment_world(replace(gen_config, horizon_min=300.0),
                                  "open_plain", 5)
    s = 90.0
    a = build_information_set(short, s)
    b = build_information_set(long, s)
    assert a.n_detections() == b.n_detections()
    for name in ("fire_detections", "weather_observations"):
        ta, tb = getattr(a, name), getattr(b, name)
        for col in ("event_time_min", "availability_time_min"):
            assert np.allclose(
                ta[col].astype(float), tb[col].astype(float)
            ), f"{name}.{col} changed when the horizon was extended"
