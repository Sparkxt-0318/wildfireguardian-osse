"""Policies, loss, paired design, records and the frontier estimator."""

from __future__ import annotations

import json

import numpy as np
import pytest

from wildfireguardian_osse.experiment.frontier import (
    CrossingKind,
    estimate_frontier,
    paired_delta,
)
from wildfireguardian_osse.experiment.loss import (
    LOSS_VERSION,
    W_MISSION_FAILED,
    W_UNNECESSARY_ACTION,
    compute_loss,
)
from wildfireguardian_osse.experiment.records import (
    RECORD_COLUMNS,
    assert_provenance,
    write_records,
)
from wildfireguardian_osse.experiment.runner import RunConfig, prepare_world, run_experiment
from wildfireguardian_osse.experiment.tuning import (
    FinalSplitTuningRefused,
    tune_baseline,
    tune_forecast_margin,
)
from wildfireguardian_osse.experiment.worlds import (
    ARCHETYPES,
    SPLITS,
    build_experiment_world,
    build_world_set,
    world_generation_audit,
)
from wildfireguardian_osse.missions.outcomes import (
    FailureReason,
    MissionKind,
    MissionResult,
)
from wildfireguardian_osse.policies.base import WaitSemantics, decision_epochs
from wildfireguardian_osse.policies.baseline import BaselineParams


# -- splits ------------------------------------------------------------------

def test_splits_partition_the_archetypes_with_no_overlap():
    members = [a for group in SPLITS.values() for a in group]
    assert sorted(members) == sorted(ARCHETYPES)
    assert len(members) == len(set(members)), "an archetype appears in two splits"


def test_geography_never_crosses_a_split():
    for split, archetypes in SPLITS.items():
        for world in build_world_set(split, 4, 123):
            assert world.archetype in archetypes
            assert world.split == split


def test_tuning_refuses_the_final_split():
    with pytest.raises(FinalSplitTuningRefused):
        tune_baseline(split="final")
    with pytest.raises(FinalSplitTuningRefused):
        tune_forecast_margin(baseline_params=BaselineParams(), split="final")


def test_world_generation_audit_classifies_every_distribution():
    audit = world_generation_audit()
    allowed = {"DATA-INFORMED", "ASSUMED", "STRESS-TEST"}
    assert audit["distributions"]
    for name, entry in audit["distributions"].items():
        assert entry["status"] in allowed, name
    # Nothing may be called Korean-anchored in the MVE.
    assert "constrained by Korean data" in audit["note"]
    assert "not Korean-anchored" in audit["note"]
    assert not any(
        e["status"] == "DATA-INFORMED" for e in audit["distributions"].values()
    )


def test_planner_visible_identifiers_carry_no_swept_value():
    for world in build_world_set("final", 6, 77):
        text = f"{world.config.name} {world.config.description} {world.config.tags}"
        assert str(int(world.config.weather.wind_speed_ms)) not in text
        assert world.config.name == "forecast_value_mve"


# -- loss --------------------------------------------------------------------

def _result(feasible: bool, travel=10.0, exposure=0.0):
    return MissionResult(
        kind=MissionKind.SELF_EVACUATION, feasible=feasible, order_time_min=30.0,
        start_time_min=40.0, end_time_min=50.0, travel_time_min=travel,
        responder_exposure_min=exposure, route_id="route_direct",
        failure_reason=FailureReason.NONE if feasible else FailureReason.ROUTE_CUT_EN_ROUTE,
    )


def test_not_ordering_costs_a_failure_only_when_threatened():
    threatened = compute_loss(
        ordered=False, order_time_min=float("nan"), result=None,
        threat_time_min=90.0, horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="",
    )
    quiet = compute_loss(
        ordered=False, order_time_min=float("nan"), result=None,
        threat_time_min=float("inf"), horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="",
    )
    assert threatened.loss == pytest.approx(W_MISSION_FAILED)
    assert threatened.failure_reason == FailureReason.NOT_ORDERED.value
    assert quiet.loss == 0.0, "correctly doing nothing is free"


def test_ordering_in_a_world_that_was_never_threatened_is_an_unnecessary_action():
    breakdown = compute_loss(
        ordered=True, order_time_min=30.0, result=_result(True),
        threat_time_min=float("inf"), horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="route_direct",
    )
    assert breakdown.unnecessary_action == 1
    assert breakdown.mission_failed == 0
    assert breakdown.excess_lead_hours == 0.0, "not double-charged with lead time"
    assert breakdown.loss == pytest.approx(W_UNNECESSARY_ACTION + 0.001 * 10.0)


def test_acting_far_too_early_is_charged_but_acting_in_time_is_not():
    prompt = compute_loss(
        ordered=True, order_time_min=100.0, result=_result(True),
        threat_time_min=120.0, horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="r",
    )
    early = compute_loss(
        ordered=True, order_time_min=0.0, result=_result(True),
        threat_time_min=120.0, horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="r",
    )
    assert prompt.excess_lead_hours == 0.0
    assert early.excess_lead_hours > 1.0
    assert early.loss > prompt.loss


def test_a_failed_mission_costs_more_than_the_same_decision_succeeding():
    """Failure dominates at equal timing, which is the ordering that matters."""
    kwargs = dict(
        ordered=True, order_time_min=100.0, threat_time_min=120.0,
        horizon_min=180.0, mission_kind=MissionKind.SELF_EVACUATION, route_id="r",
    )
    failed = compute_loss(result=_result(False), **kwargs)
    succeeded = compute_loss(result=_result(True), **kwargs)
    assert failed.loss > succeeded.loss
    assert failed.loss - succeeded.loss == pytest.approx(W_MISSION_FAILED - 0.001 * 10.0)


def test_an_extremely_premature_action_can_cost_as_much_as_a_failure():
    """A declared consequence of the weights, not an oversight.

    At 0.30 per excess hour, a mission ordered ~2.5 hours before the threat and
    exposing a responder for half an hour costs about as much as one failed
    mission.  That crossover is the point: if premature action were always
    cheaper than failure, the optimal policy would be to evacuate immediately in
    every world and the experiment would measure nothing (docs/DECISIONS.md#d-017).
    """
    failed = compute_loss(
        ordered=True, order_time_min=100.0, result=_result(False),
        threat_time_min=120.0, horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="r",
    )
    very_early = compute_loss(
        ordered=True, order_time_min=0.0, result=_result(True, exposure=30.0),
        threat_time_min=170.0, horizon_min=180.0,
        mission_kind=MissionKind.SELF_EVACUATION, route_id="r",
    )
    assert very_early.loss >= failed.loss
    assert very_early.mission_failed == 0


def test_loss_is_version_stamped():
    assert LOSS_VERSION.startswith("mve-loss-")


# -- the paired run ----------------------------------------------------------

@pytest.fixture(scope="module")
def small_run():
    cfg = RunConfig(
        experiment_id="test_run", split="development", n_worlds=3, master_seed=555,
        stage="test", include_secondary_baselines=True, include_wait_variant=True,
    )
    return run_experiment(cfg)


def test_every_policy_is_scored_against_the_same_worlds(small_run):
    rows = small_run["rows"]
    by_policy: dict[str, set] = {}
    for row in rows:
        by_policy.setdefault(row["policy_id"], set()).add(row["world_id"])
    world_sets = list(by_policy.values())
    assert all(s == world_sets[0] for s in world_sets), (
        "policies were not evaluated on the same worlds; the design is not paired"
    )


def test_both_mission_kinds_are_evaluated_in_parallel(small_run):
    kinds = {row["mission_kind"] for row in small_run["rows"]}
    assert kinds == {"self_evacuation", "assisted_evacuation"}


def test_self_evacuation_never_consumes_responder_resources(small_run):
    for row in small_run["rows"]:
        if row["mission_kind"] == "self_evacuation":
            assert row["resource_use"] == 0
            assert row["responder_exposure_min"] == 0.0


def test_every_row_carries_full_provenance(small_run):
    assert_provenance(small_run["rows"])
    for row in small_run["rows"]:
        assert row["config_hash"]
        assert row["world_generator_version"]
        assert row["policy_version"]


def test_the_oracle_is_at_least_as_good_as_the_tuned_baseline(small_run):
    rows = small_run["rows"]
    for kind in ("self_evacuation", "assisted_evacuation"):
        oracle = np.mean([
            r["loss"] for r in rows
            if r["policy_id"] == "oracle_reference" and r["mission_kind"] == kind
        ])
        baseline = np.mean([
            r["loss"] for r in rows
            if r["policy_id"] == "baseline_tuned_buffer" and r["mission_kind"] == kind
        ])
        assert oracle <= baseline + 1e-9


def test_wait_semantics_are_recorded_and_can_differ(small_run):
    semantics = {row["wait_semantics"] for row in small_run["rows"]}
    assert semantics == {"ACT_NOW", "WAIT_FOR_FORECAST"}


def test_waiting_is_never_free(small_run):
    """A policy that waits cannot order earlier than the same policy acting now."""
    rows = small_run["rows"]
    act = {
        (r["world_id"], r["mission_kind"], r["error_regime"], r["latency_min"]): r
        for r in rows
        if r["policy_id"] == "forecast_aware_feasibility" and r["wait_semantics"] == "ACT_NOW"
    }
    compared = 0
    for row in rows:
        if row["policy_id"] != "forecast_aware_feasibility":
            continue
        if row["wait_semantics"] != "WAIT_FOR_FORECAST":
            continue
        key = (row["world_id"], row["mission_kind"], row["error_regime"], row["latency_min"])
        other = act.get(key)
        if other is None or not row["ordered"] or not other["ordered"]:
            continue
        assert row["order_time_min"] >= other["order_time_min"] - 1e-9
        compared += 1
    assert compared > 0, "the comparison would be vacuous"


def test_decision_epochs_span_the_horizon():
    epochs = decision_epochs(180.0)
    assert epochs[0] == 20.0
    assert epochs[-1] <= 180.0
    assert all(b - a == 10.0 for a, b in zip(epochs, epochs[1:]))


# -- records -----------------------------------------------------------------

def test_records_round_trip_with_every_declared_column(small_run, tmp_path):
    path = write_records(small_run["rows"], tmp_path / "records.csv")
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header == list(RECORD_COLUMNS)
    assert len(path.read_text().splitlines()) == len(small_run["rows"]) + 1


def test_records_reject_a_row_without_provenance():
    with pytest.raises(AssertionError, match="provenance"):
        assert_provenance([{"experiment_id": "", "world_id": 1}])


# -- frontier ----------------------------------------------------------------

def _rows_for(deltas_by_level):
    """Synthetic rows: baseline at 0, forecast-aware at the given deltas."""
    rows = []
    for world_id in range(12):
        rows.append({
            "world_id": world_id, "policy_id": "baseline_tuned_buffer",
            "mission_kind": "self_evacuation", "forecast_mode": "NONE",
            "error_regime": "no_forecast", "latency_min": float("nan"),
            "wait_semantics": "ACT_NOW", "loss": 1.0,
        })
        for level, delta in deltas_by_level.items():
            rows.append({
                "world_id": world_id, "policy_id": "forecast_aware_feasibility",
                "mission_kind": "self_evacuation",
                "forecast_mode": "CONTROLLED_PERTURBATION", "error_regime": level,
                "latency_min": 0.0, "wait_semantics": "ACT_NOW",
                "loss": 1.0 + delta,
            })
    return rows


def test_frontier_reports_a_single_crossing():
    rows = _rows_for({"none": -0.5, "low": -0.3, "medium": 0.2, "high": 0.6})
    slices = estimate_frontier(
        rows, error_levels=["none", "low", "medium", "high"], latency_levels=[0.0],
        mission_kind="self_evacuation",
    )
    assert slices[0].kind is CrossingKind.CROSSING
    assert slices[0].crossings == (("low", "medium"),)


def test_frontier_reports_multiple_crossings():
    rows = _rows_for({"none": -0.4, "low": 0.3, "medium": -0.3, "high": 0.5})
    slices = estimate_frontier(
        rows, error_levels=["none", "low", "medium", "high"], latency_levels=[0.0],
        mission_kind="self_evacuation",
    )
    assert slices[0].kind is CrossingKind.MULTIPLE_CROSSINGS
    assert len(slices[0].crossings) == 3


def test_frontier_reports_no_crossing_when_one_sign_holds():
    rows = _rows_for({"none": -0.5, "low": -0.4, "medium": -0.3})
    slices = estimate_frontier(
        rows, error_levels=["none", "low", "medium"], latency_levels=[0.0],
        mission_kind="self_evacuation",
    )
    assert slices[0].kind is CrossingKind.NO_CROSSING
    assert "forecast-aware better" in slices[0].note


def test_frontier_reports_unresolved_rather_than_guessing():
    """Zero paired difference is not separable from noise, so nothing is claimed."""
    rows = _rows_for({"none": 0.0, "low": 0.0, "medium": 0.0})
    slices = estimate_frontier(
        rows, error_levels=["none", "low", "medium"], latency_levels=[0.0],
        mission_kind="self_evacuation",
    )
    assert slices[0].kind is CrossingKind.UNRESOLVED
    assert "no frontier is claimed" in slices[0].note


def test_paired_delta_drops_unmatched_worlds():
    rows = _rows_for({"none": -0.2})
    rows = [r for r in rows if not (r["world_id"] == 0 and r["policy_id"] == "baseline_tuned_buffer")]
    deltas, ids = paired_delta(
        rows, policy_id="forecast_aware_feasibility",
        baseline_policy_id="baseline_tuned_buffer", mission_kind="self_evacuation",
        forecast_mode="CONTROLLED_PERTURBATION", error_regime="none", latency_min=0.0,
    )
    assert 0 not in ids
    assert deltas.size == 11
