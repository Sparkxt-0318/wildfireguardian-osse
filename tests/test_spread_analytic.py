"""Front propagation: the analytically checkable behaviour."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import CENTRE, fast_scenario, validation_scenario
from wildfireguardian_osse.nature import simulate_nature
from wildfireguardian_osse.pipeline import generate_world
from wildfireguardian_osse.rng import SeedRegistry
from wildfireguardian_osse.validation.analytic import effective_speed_ratio


def _truth(cfg):
    return simulate_nature(cfg, SeedRegistry.build(cfg.master_seed, 0))


def test_uniform_no_wind_spreads_at_exactly_r0_along_the_stencil_axes():
    cfg = validation_scenario("v1_uniform_no_wind")
    truth = _truth(cfg)
    i0, j0 = truth.grid.xy_to_ij(cfg.nature.ignitions[0].x_m, cfg.nature.ignitions[0].y_m)
    arrival = truth.arrival_time_min
    r0 = cfg.nature.r0_base_m_per_min
    dx = truth.grid.cell_size_m

    for k in (1, 5, 10):
        assert arrival[i0, j0 + k] == pytest.approx(k * dx / r0, rel=1e-9)   # east
        assert arrival[i0 + k, j0] == pytest.approx(k * dx / r0, rel=1e-9)   # north
        diagonal = k * dx * np.sqrt(2.0) / r0
        assert arrival[i0 + k, j0 + k] == pytest.approx(diagonal, rel=1e-9)


def test_uniform_no_wind_is_isotropic_within_the_stencil_bound():
    cfg = validation_scenario("v1_uniform_no_wind")
    truth = _truth(cfg)
    origin = truth.grid.xy_to_ij(cfg.nature.ignitions[0].x_m, cfg.nature.ignitions[0].y_m)
    lo, hi, ratio = effective_speed_ratio(
        truth.arrival_time_min, truth.grid, origin, 150.0, 450.0
    )
    r0 = cfg.nature.r0_base_m_per_min
    assert hi <= r0 * 1.001, "no direction may spread faster than R0"
    assert ratio < 1.15, f"stencil anisotropy {ratio:.3f} exceeds the documented bound"
    assert lo > r0 * 0.85


def test_arrival_times_do_not_depend_on_the_time_step():
    """The credit ledger removes the dt dependence (docs/DECISIONS.md#d-014)."""
    coarse = _truth(fast_scenario(time={"horizon_min": 60.0, "dt_min": 1.0}))
    fine = _truth(fast_scenario(time={"horizon_min": 60.0, "dt_min": 0.25}))
    both = np.isfinite(coarse.arrival_time_min) & np.isfinite(fine.arrival_time_min)
    union = np.isfinite(coarse.arrival_time_min) | np.isfinite(fine.arrival_time_min)
    assert both.sum() / union.sum() > 0.99
    delta = np.abs(coarse.arrival_time_min[both] - fine.arrival_time_min[both])
    assert float(delta.mean()) < 0.5


def test_a_nonburnable_band_is_an_absolute_barrier():
    cfg = validation_scenario("v4_fuel_discontinuity")
    truth = _truth(cfg)
    X, _ = truth.grid.cell_centres()
    band_centre = cfg.fuels.band_position_frac * truth.grid.width_m
    beyond = X > band_centre + cfg.fuels.band_width_m / 2.0
    near_side = X < band_centre - cfg.fuels.band_width_m / 2.0
    burned = truth.burned_mask_final
    assert int(np.count_nonzero(burned & beyond)) == 0
    assert int(np.count_nonzero(burned & near_side)) > 0
    assert int(np.count_nonzero(burned & (truth.fuels.multiplier == 0.0))) == 0


def test_burned_area_increases_with_wind_speed():
    """Monotone in wind -- but only away from the domain boundary.

    A fire that reaches the edge has its area clipped, so a boundary-contact
    world will happily show *less* area at higher wind
    (``docs/FAILURE_MODES.md#G-04``).  The test asserts the absence of that
    contact rather than quietly tolerating it.
    """
    truths = [
        _truth(
            fast_scenario(
                time={"horizon_min": 40.0, "dt_min": 1.0},
                weather={"wind_speed_ms": u, "speed_sigma_ms": 0.0, "dir_sigma_deg": 0.0},
                nature={"ignitions": [{"x_m": CENTRE, "y_m": CENTRE, "time_min": 0.0}]},
            )
        )
        for u in (0.0, 2.0, 4.0, 6.0)
    ]
    assert all("boundary_contact" not in t.flags for t in truths)
    areas = [t.burned_area_ha() for t in truths]
    assert areas == sorted(areas), areas
    assert areas[-1] > areas[0] * 1.5


def test_burned_area_increases_with_the_spread_multiplier():
    areas = [
        _truth(fast_scenario(nature={"spread_multiplier": m})).burned_area_ha()
        for m in (0.5, 1.0, 1.6)
    ]
    assert areas == sorted(areas)


def test_slope_drives_spread_uphill_when_there_is_no_wind():
    """Slope alone must produce the ellipse the ROS model prescribes."""
    from wildfireguardian_osse.nature.ros import RosCoefficients, eccentricity, length_to_breadth
    from wildfireguardian_osse.validation.analytic import directional_extent

    cfg = validation_scenario("v3_slope_only")
    truth = _truth(cfg)
    origin = truth.grid.xy_to_ij(cfg.nature.ignitions[0].x_m, cfg.nature.ignitions[0].y_m)
    upslope = directional_extent(truth.arrival_time_min, truth.grid, origin, 0.0)
    downslope = directional_extent(truth.arrival_time_min, truth.grid, origin, np.pi)
    crossslope = directional_extent(truth.arrival_time_min, truth.grid, origin, np.pi / 2)
    assert upslope > crossslope > downslope

    coeffs = RosCoefficients.from_config(cfg.nature)
    phi = float(coeffs.slope_factor(np.deg2rad(cfg.terrain.slope_deg)))
    e = float(eccentricity(length_to_breadth(phi, coeffs.lb_coeff_c, coeffs.lb_exp_p)))
    expected = (1.0 + e) / (1.0 - e)
    assert upslope / downslope == pytest.approx(expected, rel=0.15)


def test_a_fire_on_a_nonburnable_cell_never_starts():
    cfg = fast_scenario(
        fuels={"kind": "uniform", "base_multiplier": 0.0},
        nature={"ignitions": [{"x_m": 500.0, "y_m": 500.0}]},
    )
    truth = _truth(cfg)
    assert int(np.count_nonzero(truth.burned_mask_final)) == 0
    assert "degenerate_no_ignition" in truth.flags


def test_boundary_contact_is_flagged():
    cfg = fast_scenario(
        weather={"wind_speed_ms": 12.0, "speed_sigma_ms": 0.0, "dir_sigma_deg": 0.0},
        time={"horizon_min": 120.0, "dt_min": 0.25},
    )
    truth = _truth(cfg)
    assert "boundary_contact" in truth.flags


def test_a_large_time_step_records_a_courant_warning():
    cfg = fast_scenario(
        weather={"wind_speed_ms": 12.0, "speed_sigma_ms": 0.0, "dir_sigma_deg": 0.0},
        time={"horizon_min": 30.0, "dt_min": 3.0},
    )
    truth = _truth(cfg)
    assert truth.spread.max_courant > 1.0
    assert any("max_courant" in w for w in truth.warnings)


def test_world_ids_produce_different_stochastic_worlds_but_identical_deterministic_ones():
    cfg = fast_scenario(weather={"speed_sigma_ms": 1.0, "dir_sigma_deg": 15.0})
    a = generate_world(cfg, 0).truth.arrival_time_min
    b = generate_world(cfg, 1).truth.arrival_time_min
    assert not np.array_equal(np.nan_to_num(a, posinf=-1), np.nan_to_num(b, posinf=-1))

    steady = fast_scenario(weather={"speed_sigma_ms": 0.0, "dir_sigma_deg": 0.0})
    c = generate_world(steady, 0).truth.arrival_time_min
    d = generate_world(steady, 1).truth.arrival_time_min
    assert np.array_equal(np.nan_to_num(c, posinf=-1), np.nan_to_num(d, posinf=-1))
