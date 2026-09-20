"""Forecast representation, the two modes, and their degradations."""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_osse.experiment.runner import prepare_world
from wildfireguardian_osse.experiment.worlds import build_experiment_world
from wildfireguardian_osse.planner import (
    ERROR_LEVELS,
    ErrorProvenanceClass,
    ErrorRegime,
    Forecast,
    ForecastProvenance,
    make_controlled_perturbation_forecast,
    make_independent_model_forecast,
    planner_sandbox,
    score_forecast,
)


@pytest.fixture(scope="module")
def prepared():
    return prepare_world(build_experiment_world(3, "plain_patchy", 4242))


def _mode_a(prepared, regime, issue=60.0, latency=0.0, horizon=90.0):
    return make_controlled_perturbation_forecast(
        truth_arrival_min=prepared.arrival,
        grid=prepared.world.geometry.grid,
        origin_xy_m=prepared.world.geometry.ignition_xy_m,
        issue_time_min=issue, horizon_min=horizon, regime=regime,
        latency_min=latency, spot_events=prepared.truth.spot_events,
    )


# -- time semantics ---------------------------------------------------------

def test_a_forecast_cannot_be_available_before_it_is_issued():
    with pytest.raises(ValueError, match="cannot be available before"):
        Forecast(
            arrival_time_min=np.zeros((2, 2)), issue_time_min=50.0,
            availability_time_min=40.0, valid_from_min=50.0, valid_to_min=90.0,
            provenance=ForecastProvenance.CONTROLLED_PERTURBATION,
            error_regime=ErrorRegime("none"),
        )


def test_a_current_state_estimate_is_not_a_forecast():
    """A forecast must describe times at or after its issue time."""
    with pytest.raises(ValueError, match="current-state estimate is not a forecast"):
        Forecast(
            arrival_time_min=np.zeros((2, 2)), issue_time_min=50.0,
            availability_time_min=50.0, valid_from_min=10.0, valid_to_min=90.0,
            provenance=ForecastProvenance.INDEPENDENT_MODEL_FORECAST,
            error_regime=ErrorRegime("none"),
        )


def test_latency_is_exactly_the_configured_delay(prepared):
    for latency in (0.0, 5.0, 30.0, 60.0):
        forecast = _mode_a(prepared, ERROR_LEVELS[0], latency=latency)
        assert forecast.latency_min == pytest.approx(latency)
        assert forecast.usable_at(forecast.issue_time_min + latency)
        if latency > 0:
            assert not forecast.usable_at(forecast.issue_time_min + latency - 1e-6)


def test_horizon_is_measured_from_the_issue_time(prepared):
    forecast = _mode_a(prepared, ERROR_LEVELS[0], issue=40.0, horizon=90.0)
    assert forecast.horizon_min == pytest.approx(90.0)
    assert forecast.valid_to_min == pytest.approx(130.0)


# -- Mode A: structured, coherent degradation -------------------------------

def test_zero_error_reproduces_the_truth_field(prepared):
    forecast = _mode_a(prepared, ErrorRegime("none"))
    assert np.array_equal(
        np.nan_to_num(forecast.arrival_time_min, posinf=-1.0),
        np.nan_to_num(prepared.arrival, posinf=-1.0),
    )


def test_skill_degrades_monotonically_along_the_declared_error_axis(prepared):
    csi = []
    for regime in ERROR_LEVELS:
        forecast = _mode_a(prepared, regime)
        csi.append(score_forecast(forecast, prepared.arrival, prepared.world.geometry.grid).csi)
    assert csi[0] == pytest.approx(1.0)
    assert csi == sorted(csi, reverse=True), csi


def test_displacement_grows_along_the_error_axis(prepared):
    displacements = []
    for regime in ERROR_LEVELS[1:]:
        forecast = _mode_a(prepared, regime)
        scores = score_forecast(forecast, prepared.arrival, prepared.world.geometry.grid)
        displacements.append(scores.front_displacement_m)
    finite = [d for d in displacements if np.isfinite(d)]
    assert len(finite) >= 3
    assert finite[-1] > finite[0]


def test_the_degradation_is_coherent_not_iid(prepared):
    """A displaced forecast is a *moved* fire, not a noisy one.

    The predicted burned area stays comparable to the truth's; IID pixel noise
    would change the area, not the position.
    """
    forecast = _mode_a(prepared, ErrorRegime("shift", 0.0, 600.0))
    truth_burned = int(np.count_nonzero(np.isfinite(prepared.arrival)))
    pred_burned = int(np.count_nonzero(np.isfinite(forecast.arrival_time_min)))
    assert pred_burned == pytest.approx(truth_burned, rel=0.25)


def test_rate_bias_moves_arrival_times_without_moving_the_fire(prepared):
    fast = _mode_a(prepared, ErrorRegime("fast", rate_bias=1.5))
    slow = _mode_a(prepared, ErrorRegime("slow", rate_bias=0.6))
    future = np.isfinite(prepared.arrival) & (prepared.arrival > 60.0)
    assert np.all(fast.arrival_time_min[future] <= prepared.arrival[future] + 1e-6)
    assert np.all(slow.arrival_time_min[future] >= prepared.arrival[future] - 1e-6)
    # the burned *set* is unchanged: this is a timing error, not a placement one
    assert np.array_equal(np.isfinite(fast.arrival_time_min), np.isfinite(prepared.arrival))


def test_missed_spotting_removes_ground_a_spot_would_have_seeded():
    """Only meaningful in a world that actually spots."""
    for world_id in range(12):
        prep = prepare_world(build_experiment_world(world_id, "plain_patchy", 4242))
        spots = [e for e in prep.truth.spot_events if e.ignited and e.time_min > 40.0]
        if not spots:
            continue
        with_spot = make_controlled_perturbation_forecast(
            truth_arrival_min=prep.arrival, grid=prep.world.geometry.grid,
            origin_xy_m=prep.world.geometry.ignition_xy_m, issue_time_min=40.0,
            horizon_min=140.0, regime=ErrorRegime("keep"), latency_min=0.0,
            spot_events=prep.truth.spot_events,
        )
        without = make_controlled_perturbation_forecast(
            truth_arrival_min=prep.arrival, grid=prep.world.geometry.grid,
            origin_xy_m=prep.world.geometry.ignition_xy_m, issue_time_min=40.0,
            horizon_min=140.0, regime=ErrorRegime("drop", missed_spotting=True),
            latency_min=0.0, spot_events=prep.truth.spot_events,
        )
        a = int(np.count_nonzero(np.isfinite(with_spot.arrival_time_min)))
        b = int(np.count_nonzero(np.isfinite(without.arrival_time_min)))
        assert b < a
        return
    pytest.skip("no world in this sample produced a post-issue spot ignition")


def test_error_families_declare_their_provenance_class():
    for regime in ERROR_LEVELS:
        assert regime.provenance_class is ErrorProvenanceClass.TOY_MECHANISM
        payload = regime.as_dict()
        assert payload["error_provenance_class"] == "TOY_MECHANISM"
    # No family claims empirical or learned support in the MVE.
    assert all(
        r.provenance_class
        not in (ErrorProvenanceClass.EMPIRICALLY_MOTIVATED, ErrorProvenanceClass.LEARNED)
        for r in ERROR_LEVELS
    )


# -- Mode B: an independent model -------------------------------------------

def test_mode_b_uses_only_available_data(prepared):
    with planner_sandbox():
        early = make_independent_model_forecast(
            data=prepared.view.at(30.0), grid=prepared.world.geometry.grid,
            issue_time_min=30.0, horizon_min=90.0, latency_min=0.0,
        )
        late = make_independent_model_forecast(
            data=prepared.view.at(120.0), grid=prepared.world.geometry.grid,
            issue_time_min=120.0, horizon_min=90.0, latency_min=0.0,
        )
    assert late is not None
    if early is not None:
        assert (
            early.diagnostics["n_detections_used"]
            <= late.diagnostics["n_detections_used"] + 1
        )


def test_mode_b_returns_none_when_it_cannot_forecast(prepared):
    """No detections yet is a result, not an error: the planner must cope."""
    with planner_sandbox():
        forecast = make_independent_model_forecast(
            data=prepared.view.at(0.0), grid=prepared.world.geometry.grid,
            issue_time_min=0.0, horizon_min=90.0, latency_min=0.0,
        )
    assert forecast is None


def test_mode_b_is_structurally_different_from_nature(prepared):
    """Its skill is well below a perfect forecast: it is not truth in disguise."""
    with planner_sandbox():
        forecast = make_independent_model_forecast(
            data=prepared.view.at(70.0), grid=prepared.world.geometry.grid,
            issue_time_min=70.0, horizon_min=90.0, latency_min=0.0,
        )
    scores = score_forecast(forecast, prepared.arrival, prepared.world.geometry.grid)
    assert 0.0 <= scores.csi < 0.9
    diagnostics = forecast.diagnostics
    assert "planner_head_rate_m_per_min" in diagnostics
    assert "planner_eccentricity" in diagnostics


def test_mode_b_predicts_beyond_what_it_has_seen(prepared):
    """Its valid window starts at issue time: it forecasts, not just estimates."""
    with planner_sandbox():
        forecast = make_independent_model_forecast(
            data=prepared.view.at(70.0), grid=prepared.world.geometry.grid,
            issue_time_min=70.0, horizon_min=90.0, latency_min=0.0,
        )
    field = forecast.arrival_time_min
    future = np.isfinite(field) & (field > forecast.issue_time_min)
    assert int(np.count_nonzero(future)) > 50
