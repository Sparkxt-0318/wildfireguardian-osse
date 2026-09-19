"""Stochastic spotting (``docs/NATURE_MODEL.md#5``)."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import fast_scenario
from wildfireguardian_osse.pipeline import generate_world


def _spotting(**params):
    base = {
        "enabled": True,
        "interval_min": 10.0,
        "rate_per_ha_per_min": 0.02,
        "median_distance_m": 300.0,
        "p_ignite": 0.7,
    }
    base.update(params)
    return fast_scenario(nature={"spotting": base})


def test_disabled_spotting_consumes_no_randomness_and_changes_nothing():
    """`enabled: false` must be exactly a model without spotting."""
    off = generate_world(fast_scenario(nature={"spotting": {"enabled": False}}), 0)
    # Changing every other spotting parameter must be a no-op while disabled.
    other = generate_world(
        fast_scenario(
            nature={
                "spotting": {
                    "enabled": False,
                    "rate_per_ha_per_min": 5.0,
                    "median_distance_m": 900.0,
                    "p_ignite": 1.0,
                }
            }
        ),
        0,
    )
    assert off.truth.spot_events == []
    assert np.array_equal(
        np.nan_to_num(off.truth.arrival_time_min, posinf=-1.0),
        np.nan_to_num(other.truth.arrival_time_min, posinf=-1.0),
    )


def test_enabled_spotting_ignites_and_grows_the_fire():
    off = generate_world(fast_scenario(nature={"spotting": {"enabled": False}}), 0)
    on = generate_world(_spotting(), 0)
    ignited = [e for e in on.truth.spot_events if e.ignited]
    assert len(ignited) >= 1
    assert on.truth.burned_area_ha() >= off.truth.burned_area_ha()


def test_every_attempt_is_recorded_with_its_outcome():
    world = generate_world(_spotting(p_ignite=0.3), 0)
    reasons = {e.reason for e in world.truth.spot_events}
    assert reasons <= {
        "ignited", "outside_domain", "already_burned", "nonburnable", "no_ignition"
    }
    assert "no_ignition" in reasons, "a low p_ignite must produce failed attempts"
    for event in world.truth.spot_events:
        assert event.ignited == (event.reason == "ignited")


def test_spot_ignitions_land_downwind():
    world = generate_world(_spotting(bearing_sigma_deg=5.0), 0)
    offsets = [
        e.land_x_m - e.origin_x_m for e in world.truth.spot_events if e.ignited
    ]
    assert len(offsets) >= 3
    assert float(np.mean(offsets)) > 0.0  # wind blows toward +x in fast_scenario


def test_spot_distance_tracks_the_median_distance():
    near = generate_world(_spotting(median_distance_m=150.0), 0)
    far = generate_world(_spotting(median_distance_m=600.0), 0)
    dn = np.array([e.distance_m for e in near.truth.spot_events])
    df = np.array([e.distance_m for e in far.truth.spot_events])
    assert dn.size > 3 and df.size > 3
    assert float(np.median(dn)) == pytest.approx(150.0, rel=0.45)
    assert float(np.median(df)) == pytest.approx(600.0, rel=0.45)


def test_spot_rate_controls_the_number_of_attempts():
    counts = [
        len(generate_world(_spotting(rate_per_ha_per_min=r), 0).truth.spot_events)
        for r in (0.002, 0.02, 0.08)
    ]
    assert counts == sorted(counts)
    assert counts[-1] > counts[0]


def test_spotting_never_ignites_a_nonburnable_cell():
    world = generate_world(
        _spotting(rate_per_ha_per_min=0.08),
        0,
    )
    for event in world.truth.spot_events:
        if event.ignited:
            i, j = world.truth.grid.xy_to_ij(event.land_x_m, event.land_y_m)
            assert world.truth.fuels.burnable[i, j]


def test_spotting_uses_its_own_stream():
    """Changing the sensor configuration must not move a single firebrand."""
    a = generate_world(_spotting(), 0)
    b = generate_world(_spotting(), 0)
    assert [e.to_dict() for e in a.truth.spot_events] == [e.to_dict() for e in b.truth.spot_events]

    noisy = fast_scenario(
        nature={"spotting": {"enabled": True, "interval_min": 10.0,
                             "rate_per_ha_per_min": 0.02,
                             "median_distance_m": 300.0, "p_ignite": 0.7}},
        observations={"fire_sensors": [{"sensor_id": "fire_sensor_a",
                                        "pixel_size_m": 240.0,
                                        "geoloc_sigma_m": 900.0,
                                        "p_detect_max": 0.1}]},
    )
    c = generate_world(noisy, 0)
    assert [e.to_dict() for e in a.truth.spot_events] == [e.to_dict() for e in c.truth.spot_events]


def test_spot_ignitions_are_not_written_to_a_planner_file(written_world):
    import json

    payload = json.loads((written_world / "truth/ignitions.json").read_text())
    assert "spot_events" in payload
    for rel in (written_world / "observations").rglob("*"):
        if rel.is_file() and rel.suffix in (".csv", ".json"):
            text = rel.read_text(encoding="utf-8", errors="replace").lower()
            assert "spot" not in text
