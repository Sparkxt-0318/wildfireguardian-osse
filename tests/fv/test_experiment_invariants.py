"""Runtime invariants of the paired experiment (PROTOCOL.md section 12)."""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_fv.degradation import DegradationSpec, ErrorGrid
from wildfireguardian_fv.forecast import Forecast
from wildfireguardian_fv.info import build_information_set
from wildfireguardian_fv.loss import LossComponents, LossWeights
from wildfireguardian_fv.planner import (
    ControlledPerturbationForecaster,
    IndependentPlanner,
)
from wildfireguardian_fv.policy import BaselinePolicy, run_policy
from wildfireguardian_fv.policy.forecast_aware import (
    ForecastAwareParams,
    ForecastAwarePolicy,
)
from wildfireguardian_fv.runner import (
    assert_forecast_latency,
    run_condition,
)
from wildfireguardian_fv.splits import (
    ARCHETYPE_SPLIT,
    FinalSplitViolation,
    archetypes_for,
    final_split_unlocked,
    note_final_split_read,
)


def test_splits_are_disjoint_by_archetype():
    seen: set[str] = set()
    for split in ("development", "validation", "final"):
        archetypes = set(archetypes_for(split))
        assert not (archetypes & seen), "an archetype appears in two splits"
        seen |= archetypes
    assert seen == set(ARCHETYPE_SPLIT)


def test_final_split_is_locked_by_default():
    with pytest.raises(FinalSplitViolation):
        note_final_split_read("a tuning routine")


def test_final_split_unlocks_only_inside_the_context():
    with final_split_unlocked("test"):
        note_final_split_read("frozen evaluation")
    with pytest.raises(FinalSplitViolation):
        note_final_split_read("a tuning routine")


def test_tuning_refuses_non_validation_worlds(dev_world):
    from wildfireguardian_fv.tuning import tune_baseline

    with pytest.raises(AssertionError):
        tune_baseline([dev_world])


def test_both_policies_run_against_the_same_world(dev_world):
    res = run_condition(
        dev_world,
        DegradationSpec(label="t"),
        "INDEPENDENT_MODEL_FORECAST",
        baseline=BaselinePolicy(),
        forecast_params=ForecastAwareParams(),
        planner=IndependentPlanner(),
        perturber=ControlledPerturbationForecaster(),
        weights=LossWeights(),
    )
    assert res.baseline.world_id == res.forecast_aware.world_id == dev_world.world_id
    base_ids = [t.resident_id for t in res.baseline.traces]
    fc_ids = [t.resident_id for t in res.forecast_aware.traces]
    assert base_ids == fc_ids
    for t in res.baseline.traces:
        other = next(u for u in res.forecast_aware.traces
                     if u.resident_id == t.resident_id)
        assert t.truth_arrival_at_house_min == other.truth_arrival_at_house_min, (
            "the two policies saw different hidden futures"
        )


def test_baseline_is_invariant_to_the_condition(dev_world):
    """The baseline consumes no forecast, so theta must not move it."""
    baseline = BaselinePolicy()
    weights = LossWeights()
    reference = run_policy(dev_world, baseline, weights).mean_loss(weights)
    for spec in ErrorGrid().points()[:6]:
        res = run_condition(
            dev_world, spec, "INDEPENDENT_MODEL_FORECAST",
            baseline=baseline,
            forecast_params=ForecastAwareParams(),
            planner=IndependentPlanner(),
            perturber=ControlledPerturbationForecaster(),
            weights=weights,
        )
        assert res.baseline.mean_loss(weights) == pytest.approx(reference)


@pytest.mark.parametrize("latency", [0.0, 5.0, 30.0, 60.0])
def test_forecast_latency_is_applied_exactly(dev_world, latency):
    planner = IndependentPlanner()
    spec = DegradationSpec(latency_min=latency, label=f"d{latency:g}")
    policy = ForecastAwarePolicy(
        forecast_source=lambda info: planner.forecast(info, spec)
    )
    policy.reset()
    run_policy(dev_world, policy)
    issued = [f for f in policy._issued.values() if f is not None]
    assert issued
    assert_forecast_latency(issued, latency)
    for f in issued:
        assert not f.usable_at(f.issue_time_min - 1e-6)
        assert f.usable_at(f.availability_time_min)
        if latency > 0:
            assert not f.usable_at(f.availability_time_min - 1e-6)


def test_a_forecast_must_be_about_the_future():
    with pytest.raises(ValueError):
        Forecast(
            forecast_id="x", mode="INDEPENDENT_MODEL_FORECAST", status="ISSUED",
            issue_time_min=60.0, availability_time_min=60.0,
            valid_from_min=30.0, valid_to_min=120.0, cell_size_m=120.0,
            predicted_arrival_time_min=np.zeros((2, 2)),
        )


def test_a_forecast_cannot_be_available_before_it_is_issued():
    with pytest.raises(ValueError):
        Forecast(
            forecast_id="x", mode="INDEPENDENT_MODEL_FORECAST", status="ISSUED",
            issue_time_min=60.0, availability_time_min=50.0,
            valid_from_min=60.0, valid_to_min=120.0, cell_size_m=120.0,
            predicted_arrival_time_min=np.zeros((2, 2)),
        )


def test_policy_decisions_are_reproducible(dev_world):
    weights = LossWeights()
    a = run_policy(dev_world, BaselinePolicy(), weights)
    b = run_policy(dev_world, BaselinePolicy(), weights)
    assert [t.action for t in a.traces] == [t.action for t in b.traces]
    assert a.mean_loss(weights) == pytest.approx(b.mean_loss(weights))


def test_world_generation_is_reproducible(gen_config):
    from wildfireguardian_fv.worlds import build_experiment_world

    a = build_experiment_world(gen_config, "open_plain", 7)
    b = build_experiment_world(gen_config, "open_plain", 7)
    assert np.array_equal(
        np.nan_to_num(a.truth.arrival_time_min, posinf=-1.0),
        np.nan_to_num(b.truth.arrival_time_min, posinf=-1.0),
    )
    assert a.config.config_hash() == b.config.config_hash()
    assert a.village.as_planner_dict() == b.village.as_planner_dict()


def test_loss_has_no_mortality_term(conftest_executable_source):
    """The loss must stay in terms the laboratory can defend."""
    from wildfireguardian_fv import loss as loss_module

    code = conftest_executable_source(loss_module).lower()
    names = " ".join(LossComponents.__dataclass_fields__)
    for banned in ("mortality", "lives_saved", "death", "casualt", "fatalit"):
        assert banned not in code, f"the loss must not model {banned}"
        assert banned not in names


def test_self_evacuation_is_not_inferred_from_route_existence(dev_world):
    """Capability and route existence are independent facts."""
    res = run_policy(dev_world, BaselinePolicy())
    incapable = {
        r.resident_id
        for r in dev_world.village.residents
        if not r.self_evacuation_capable
    }
    for t in res.traces:
        if t.resident_id in incapable:
            assert t.self_evacuation_state == "RESIDENT_NOT_SELF_EVACUATION_CAPABLE"
        assert t.outcome_state != "SAFE"


def test_per_mode_parameters_are_used_per_mode(dev_world):
    """A parameter set per forecast mode must actually reach that mode.

    Tuning the forecast-aware policy only against the weaker forecast and then
    applying those parameters to the stronger one confounds "an accurate
    forecast is not worth acting on" with "this policy was set up not to act on
    one" (PROTOCOL.md section 18).
    """
    from wildfireguardian_fv.runner import run_experiment

    never = ForecastAwareParams(lead_min=0.0, visible_threat_buffer_m=0.0)
    always = ForecastAwareParams(lead_min=240.0, visible_threat_buffer_m=5000.0)
    out = run_experiment(
        [dev_world],
        experiment_id="per_mode",
        grid=ErrorGrid(direction_bias_deg=(0.0,), latency_min=(0.0,)),
        modes=["INDEPENDENT_MODEL_FORECAST", "CONTROLLED_PERTURBATION"],
        baseline=BaselinePolicy(),
        forecast_params={
            "INDEPENDENT_MODEL_FORECAST": never,
            "CONTROLLED_PERTURBATION": always,
        },
        weights=LossWeights(),
    )
    by_mode = {}
    for r in out.rows:
        if r.values["forecast_mode"] == "NONE":
            continue
        by_mode.setdefault(r.values["forecast_mode"], []).append(
            r.values["dispatched"]
        )
    assert sum(by_mode["INDEPENDENT_MODEL_FORECAST"]) == 0
    assert sum(by_mode["CONTROLLED_PERTURBATION"]) > 0


def test_a_missing_mode_in_per_mode_parameters_fails_loudly(dev_world):
    from wildfireguardian_fv.runner import run_experiment

    with pytest.raises(KeyError):
        run_experiment(
            [dev_world],
            experiment_id="missing",
            grid=ErrorGrid(direction_bias_deg=(0.0,), latency_min=(0.0,)),
            modes=["CONTROLLED_PERTURBATION"],
            baseline=BaselinePolicy(),
            forecast_params={"INDEPENDENT_MODEL_FORECAST": ForecastAwareParams()},
            weights=LossWeights(),
        )
