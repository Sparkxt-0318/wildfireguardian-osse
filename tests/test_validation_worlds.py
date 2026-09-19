"""The eight validation worlds (``docs/VALIDATION.md#1``).

Generated once per session because they are the largest worlds in the suite.
"""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_osse.nature.ros import (
    RosCoefficients,
    eccentricity,
    length_to_breadth,
)
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.scenarios.library import (
    build_validation_scenario,
    validation_scenario_names,
)
from wildfireguardian_osse.validation.analytic import (
    burned_centroid,
    directional_extent,
    effective_speed_ratio,
    principal_axis_deg,
)


@pytest.fixture(scope="module")
def worlds():
    return {
        name: generate_world(build_validation_scenario(name), k)
        for k, name in enumerate(validation_scenario_names())
    }


def _origin(world):
    ignition = world.config.nature.ignitions[0]
    return world.truth.grid.xy_to_ij(ignition.x_m, ignition.y_m)


def _expected_head_back_ratio(world, wind_ms: float) -> float:
    coeffs = RosCoefficients.from_config(world.config.nature)
    phi = coeffs.wind_factor(wind_ms)
    e = float(eccentricity(length_to_breadth(phi, coeffs.lb_coeff_c, coeffs.lb_exp_p)))
    return (1.0 + e) / (1.0 - e)


def test_no_validation_world_touches_the_domain_boundary(worlds):
    """A clipped fire invalidates every shape expectation below."""
    clipped = [n for n, w in worlds.items() if "boundary_contact" in w.truth.flags]
    assert clipped == []


def test_no_validation_world_is_outside_the_discretisation_envelope(worlds):
    noisy = {n: w.truth.warnings for n, w in worlds.items() if w.truth.warnings}
    assert noisy == {}


# -- V1 ---------------------------------------------------------------------

def test_v1_is_isotropic(worlds):
    world = worlds["v1_uniform_no_wind"]
    r0 = world.config.nature.r0_base_m_per_min
    lo, hi, ratio = effective_speed_ratio(
        world.truth.arrival_time_min, world.truth.grid, _origin(world), 150.0, 500.0
    )
    assert hi <= r0 * 1.001
    assert ratio < 1.15
    assert lo > r0 * 0.85


# -- V2 ---------------------------------------------------------------------

def test_v2_is_elongated_downwind_by_the_prescribed_ratio(worlds):
    world = worlds["v2_uniform_constant_wind"]
    origin = _origin(world)
    arrival, grid = world.truth.arrival_time_min, world.truth.grid
    head = directional_extent(arrival, grid, origin, 0.0)
    back = directional_extent(arrival, grid, origin, np.pi)
    flank = directional_extent(arrival, grid, origin, np.pi / 2)
    assert head > flank > back
    expected = _expected_head_back_ratio(world, world.config.weather.wind_speed_ms)
    assert head / back == pytest.approx(expected, rel=0.20)

    cx, _ = burned_centroid(arrival, grid)
    ignition_x = world.config.nature.ignitions[0].x_m
    assert cx > ignition_x, "centroid must sit downwind of the ignition"


# -- V3 ---------------------------------------------------------------------

def test_v3_spreads_upslope(worlds):
    world = worlds["v3_slope_only"]
    origin = _origin(world)
    arrival, grid = world.truth.arrival_time_min, world.truth.grid
    up = directional_extent(arrival, grid, origin, 0.0)       # aspect is east
    down = directional_extent(arrival, grid, origin, np.pi)
    cross = directional_extent(arrival, grid, origin, np.pi / 2)
    assert up > cross > down

    coeffs = RosCoefficients.from_config(world.config.nature)
    phi = float(coeffs.slope_factor(np.deg2rad(world.config.terrain.slope_deg)))
    e = float(eccentricity(length_to_breadth(phi, coeffs.lb_coeff_c, coeffs.lb_exp_p)))
    assert up / down == pytest.approx((1 + e) / (1 - e), rel=0.15)


# -- V4 ---------------------------------------------------------------------

def test_v4_barrier_is_absolute(worlds):
    world = worlds["v4_fuel_discontinuity"]
    truth, cfg = world.truth, world.config
    X, _ = truth.grid.cell_centres()
    centre = cfg.fuels.band_position_frac * truth.grid.width_m
    half = cfg.fuels.band_width_m / 2.0
    burned = truth.burned_mask_final
    assert int(np.count_nonzero(burned & (X > centre + half))) == 0
    assert int(np.count_nonzero(burned & (X < centre - half))) > 0
    # the fire must actually have reached the barrier, or the test is vacuous
    reached = burned & (X > centre - half - 2 * truth.grid.cell_size_m)
    assert int(np.count_nonzero(reached)) > 0


# -- V5 ---------------------------------------------------------------------

def test_v5_growth_direction_follows_the_wind_shift(worlds):
    world = worlds["v5_wind_shift"]
    horizon = world.config.time.horizon_min
    arrival, grid = world.truth.arrival_time_min, world.truth.grid
    first = principal_axis_deg(arrival, grid, horizon * 0.15, horizon * 0.5)
    second = principal_axis_deg(arrival, grid, horizon * 0.55, horizon)
    assert np.isfinite(first) and np.isfinite(second)
    turn = abs((second - first + 180.0) % 360.0 - 180.0)
    assert turn > 45.0, f"growth direction turned only {turn:.1f} degrees"
    # the schedule veers from east (0 deg) to north (90 deg)
    assert first == pytest.approx(0.0, abs=35.0) or first == pytest.approx(360.0, abs=35.0)
    assert second == pytest.approx(90.0, abs=35.0)


# -- V6 / V7 ----------------------------------------------------------------

def test_v6_has_no_spotting_at_all(worlds):
    world = worlds["v6_spotting_off"]
    assert world.truth.spot_events == []
    assert world.config.nature.spotting.enabled is False


def test_v7_spots_and_burns_at_least_as_much_as_v6(worlds):
    on, off = worlds["v7_spotting_on"], worlds["v6_spotting_off"]
    ignited = [e for e in on.truth.spot_events if e.ignited]
    assert len(ignited) >= 1
    assert on.truth.burned_area_ha() >= off.truth.burned_area_ha()


def test_v7_ignites_ahead_of_the_main_front(worlds):
    """At least one spot lands on ground the main front had not reached."""
    on, off = worlds["v7_spotting_on"], worlds["v6_spotting_off"]
    grid = on.truth.grid
    ahead = 0
    for event in on.truth.spot_events:
        if not event.ignited:
            continue
        i, j = grid.xy_to_ij(event.land_x_m, event.land_y_m)
        if off.truth.arrival_time_min[i, j] > event.time_min:
            ahead += 1
    assert ahead >= 1


# -- V8 ---------------------------------------------------------------------

def test_v8_outage_touches_only_the_observation_layer(worlds):
    outage, clean = worlds["v8_sensor_outage"], worlds["v6_spotting_off"]
    a = np.nan_to_num(outage.truth.arrival_time_min, posinf=-1.0)
    b = np.nan_to_num(clean.truth.arrival_time_min, posinf=-1.0)
    assert np.array_equal(a, b), "a sensor outage must not change the fire"


def test_v8_has_a_contiguous_run_of_suppressed_scans(worlds):
    world = worlds["v8_sensor_outage"]
    log = world.observations.fire_scan_log.sort_by("event_time_min")
    status = [str(s) for s in log.columns["status"]]
    assert "outage" in status
    runs, current = [], 0
    for s in status:
        current = current + 1 if s == "outage" else 0
        runs.append(current)
    assert max(runs) >= 2, f"expected a run of >=2 outage scans, got {status}"
    assert world.observations.n_detections() < worlds["v6_spotting_off"].observations.n_detections()
