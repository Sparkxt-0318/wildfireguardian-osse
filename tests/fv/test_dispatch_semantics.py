"""Mission feasibility semantics, belief side and truth side."""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_fv.dispatch import (
    ArrivalTimeHazard,
    MissionFeasibilityAdapter,
    PlaceholderDispatchAdapter,
    classify_outcome,
)
from wildfireguardian_fv.rng import FvSeedRegistry
from wildfireguardian_fv.village import VillageConfig, build_village


@pytest.fixture(scope="module")
def village():
    rng = FvSeedRegistry.build(1, 0).generator("world_layout_seed", "village")
    return build_village(VillageConfig(), 5760.0, 5760.0, rng)


def _clear(shape=(48, 48)) -> ArrivalTimeHazard:
    return ArrivalTimeHazard(np.full(shape, np.inf), 120.0, "TEST_CLEAR")


def test_placeholder_satisfies_the_adapter_contract():
    assert isinstance(PlaceholderDispatchAdapter(), MissionFeasibilityAdapter)


def test_a_mission_completes_when_nothing_is_burning(village):
    out = PlaceholderDispatchAdapter().plan_and_evaluate(
        village, _clear(), village.residents[0].resident_id, 0.0, 240.0
    )
    assert out.feasible and out.reason == "COMPLETED"
    assert out.plan.pickup_end_min - out.plan.pickup_start_min == pytest.approx(
        village.residents[0].pickup_duration_min
    )


def test_full_interval_semantics_is_stricter_than_point_in_time(village):
    """Fire arriving behind the vehicle blocks the edge under the contract default.

    Exercised on a single edge rather than through a whole mission, so the
    result is about the semantics and not about which other edge happened to
    share a 120 m hazard cell.
    """
    from wildfireguardian_fv.dispatch import _edge_passable

    edge = next(e for e in village.edges if e.road_class == "spine")
    t_enter, t_exit = 10.0, 10.0 + edge.travel_time_min
    # Fire reaches the *start* of the corridor just before the vehicle leaves
    # the far end: behind the vehicle, but inside the traversal interval.
    field = np.full((48, 48), np.inf)
    x, y = edge.sample_xy_m[0]
    field[int(y // 120), int(x // 120)] = t_exit - 1e-3
    hazard = ArrivalTimeHazard(field, 120.0, "TEST")

    assert not _edge_passable(hazard, edge, t_enter, t_exit, "FULL_INTERVAL")
    assert _edge_passable(hazard, edge, t_enter, t_exit, "POINT_IN_TIME"), (
        "point-in-time semantics only requires beating the fire to each point"
    )

    after = np.full((48, 48), np.inf)
    after[int(y // 120), int(x // 120)] = t_exit + 1e-3
    clear_after = ArrivalTimeHazard(after, 120.0, "TEST")
    assert _edge_passable(hazard=clear_after, edge=edge, t_enter_min=t_enter,
                          t_exit_min=t_exit, semantics="FULL_INTERVAL")


def test_a_plan_made_under_one_field_is_replayable_against_another(village):
    """The paired-world workhorse: same plan, different hazard."""
    adapter = PlaceholderDispatchAdapter()
    rid = village.residents[0].resident_id
    belief = adapter.plan_and_evaluate(village, _clear(), rid, 0.0, 240.0)
    burning = ArrivalTimeHazard(np.zeros((48, 48)), 120.0, "ALL_BURNING")
    truth_side = adapter.evaluate_plan(village, burning, belief.plan)
    assert belief.feasible and not truth_side.feasible
    assert truth_side.plan is belief.plan


def test_fire_at_the_house_before_pickup_completes_is_a_failure(village):
    adapter = PlaceholderDispatchAdapter()
    r = village.residents[0]
    field = np.full((48, 48), np.inf)
    field[int(r.y_m // 120), int(r.x_m // 120)] = 1.0
    out = adapter.plan_and_evaluate(
        village, ArrivalTimeHazard(field, 120.0, "T"), r.resident_id, 0.0, 240.0
    )
    assert not out.feasible
    assert out.reason == "FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE", (
        "a burning house must be reported as such, not as a routing failure: "
        "the failure taxonomy is what FAILURE_ANALYSIS.md is built from"
    )


def test_self_evacuation_requires_capability_not_just_a_route(village):
    adapter = PlaceholderDispatchAdapter()
    for r in village.residents:
        out = adapter.self_evacuation_feasible(
            village, _clear(), r.resident_id, 0.0, 600.0
        )
        if not r.self_evacuation_capable:
            assert out.reason == "RESIDENT_NOT_SELF_EVACUATION_CAPABLE"


def test_outcome_vocabulary_never_says_safe(village):
    adapter = PlaceholderDispatchAdapter()
    r = village.residents[0]
    assisted = adapter.plan_and_evaluate(village, _clear(), r.resident_id, 0.0, 240.0)
    self_evac = adapter.self_evacuation_feasible(
        village, _clear(), r.resident_id, 0.0, 600.0
    )
    state = classify_outcome(assisted, self_evac)
    assert state in (
        "SELF_EVACUATION_FEASIBLE", "ASSISTANCE_FEASIBLE", "BOTH_FEASIBLE",
        "ROUTE_EVIDENCE_UNRESOLVED", "NO_FEASIBLE_MISSION_FOUND",
    )


def test_village_graph_is_connected(village):
    from wildfireguardian_fv.village import _connected

    assert _connected(village.nodes, village.edges)


def test_waiting_costs_time(village):
    """Dispatching later cannot complete earlier -- waiting is never free."""
    adapter = PlaceholderDispatchAdapter()
    rid = village.residents[0].resident_id
    early = adapter.plan_and_evaluate(village, _clear(), rid, 0.0, 240.0)
    late = adapter.plan_and_evaluate(village, _clear(), rid, 30.0, 240.0)
    assert late.plan.completion_time_min > early.plan.completion_time_min
