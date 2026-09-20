"""Mode B must be a genuinely different model, not nature with noise."""

from __future__ import annotations

import math

import numpy as np
import pytest

from wildfireguardian_fv.degradation import DegradationSpec
from wildfireguardian_fv.info import build_information_set, truth_access_guard
from wildfireguardian_fv.planner import IndependentPlanner
from wildfireguardian_fv.planner.independent import PlannerCoefficients
from wildfireguardian_fv.skill import score_forecast


def test_planner_runs_under_the_truth_access_guard(dev_world):
    info = build_information_set(dev_world, 90.0)
    with truth_access_guard():
        f = IndependentPlanner().forecast(info, DegradationSpec())
    assert f.mode == "INDEPENDENT_MODEL_FORECAST"


def test_planner_output_depends_only_on_the_information_set(dev_world):
    """Two planners fed the same D_s must agree exactly."""
    info = build_information_set(dev_world, 90.0)
    a = IndependentPlanner().forecast(info, DegradationSpec())
    b = IndependentPlanner().forecast(info, DegradationSpec())
    assert np.array_equal(
        np.nan_to_num(a.predicted_arrival_time_min, posinf=-1.0),
        np.nan_to_num(b.predicted_arrival_time_min, posinf=-1.0),
    )


def test_planner_rate_law_differs_from_natures(dev_world):
    """A different functional form, not a re-parameterisation of nature's."""
    coeff = PlannerCoefficients()
    nat = dev_world.config.nature
    for u in (2.0, 4.0, 6.0):
        planner_rate = coeff.r0_m_per_min + coeff.k_wind_m_per_min_per_ms * u
        nature_rate = nat.r0_base_m_per_min * (
            1.0 + nat.wind_coeff_a * u**nat.wind_exp_b
        )
        assert abs(planner_rate - nature_rate) > 0.5, (
            f"at wind {u} m/s the planner and nature rates agree to within "
            "0.5 m/min; the planner is not structurally independent"
        )


def test_planner_is_blind_to_terrain(conftest_executable_source):
    """The planner has no terrain term in its *code*.

    Checked against the executable source with docstrings stripped: a test
    that matched on prose would fail whenever the documentation got better,
    which is exactly backwards.
    """
    from wildfireguardian_fv.planner import independent

    code = conftest_executable_source(independent).lower()
    for banned in ("slope", "elevation_m", "upslope", "aspect", "terrain"):
        assert banned not in code, (
            f"the independent planner must not use {banned}: nature's "
            "slope-driven anisotropy is a declared structural blind spot"
        )


def test_planner_has_no_spotting_term(conftest_executable_source):
    from wildfireguardian_fv.planner import independent

    code = conftest_executable_source(independent).lower()
    for banned in ("spot_event", "spotting", "firebrand"):
        assert banned not in code


def test_planner_forecast_is_imperfect(dev_world):
    """Emergent error: a structurally different model should not score 1.0."""
    info = build_information_set(dev_world, 90.0)
    f = IndependentPlanner().forecast(info, DegradationSpec())
    scores = score_forecast(dev_world, f)
    if scores.csi != scores.csi:  # NaN: nothing burned in the window
        pytest.skip("valid window contained no truth arrivals")
    assert scores.csi < 0.99, (
        "the independent planner reproduced the hidden field almost exactly; "
        "check that it is not reading truth"
    )


def test_direction_bias_rotates_the_predicted_pattern(dev_world):
    info = build_information_set(dev_world, 120.0)
    plain = IndependentPlanner().forecast(info, DegradationSpec())
    turned = IndependentPlanner().forecast(
        info, DegradationSpec(direction_bias_deg=45.0, label="e45")
    )
    a = plain.diagnostics["heading_deg"]
    b = turned.diagnostics["heading_deg"]
    assert math.isclose((b - a) % 360.0, 45.0, abs_tol=1e-6)


def test_no_fire_evidence_yields_an_explicit_empty_forecast(dev_world):
    info = build_information_set(dev_world, 0.0)
    f = IndependentPlanner().forecast(info, DegradationSpec())
    assert f.status == "NO_FIRE_EVIDENCE"
    assert not np.isfinite(f.predicted_arrival_time_min).any()


def test_mode_a_is_labelled_as_built_from_truth(dev_world):
    from wildfireguardian_fv.planner import ControlledPerturbationForecaster

    f = ControlledPerturbationForecaster().forecast(
        dev_world, 90.0, DegradationSpec(label="t")
    )
    assert f.mode == "CONTROLLED_PERTURBATION"
    assert "CONTROLLED_PERTURBATION" in f.provenance
