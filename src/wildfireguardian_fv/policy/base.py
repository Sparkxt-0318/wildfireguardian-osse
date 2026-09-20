"""The shared decision loop, and the act-now / wait semantics.

    for s in decision times:
        D_s  = build_information_set(world, s)          # the only gate
        act  = policy.decide(D_s, pending residents)    # inside truth guard
        commit any ACT_NOW missions, planned under the policy's own belief
    replay every committed plan against hidden truth

Two semantics are distinguished explicitly (PROTOCOL.md section 4.3):

``ACT_NOW``
    Commit a mission at this decision time, planned under the belief the
    policy holds now.
``WAIT_FOR_FORECAST``
    Take no action this step and re-decide at the next one.  **Waiting is not
    free**: the loop advances real time, the hidden fire grows, and routes
    that were open can close.  A policy that waits pays for it in the same
    currency as everything else.

There is one commitment per resident: no replanning after dispatch.  That is a
declared limitation, not an oversight (LIMITATIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..dispatch import (
    ArrivalTimeHazard,
    MissionOutcome,
    MissionPlan,
    PlaceholderDispatchAdapter,
    classify_outcome,
)
from ..info import InformationSet, build_information_set, truth_access_guard
from ..loss import LossComponents, LossWeights
from ..world import ExperimentWorld

#: Decision cadence, minutes.  Finer than the 15 min sensor cadence, so a
#: policy can react to a product as soon as it becomes available rather than
#: on the next scan.
DECISION_INTERVAL_MIN = 5.0

ACTIONS = ("ACT_NOW", "WAIT_FOR_FORECAST", "NO_ACTION")


@dataclass(frozen=True)
class Decision:
    """What a policy decided about one resident at one information time."""

    resident_id: str
    action: str
    reason: str
    plan: MissionPlan | None = None

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}; expected {ACTIONS}")


class Policy(Protocol):
    """What every policy in this package must provide."""

    policy_id: str

    def decide(
        self, info: InformationSet, pending: tuple[str, ...], s_min: float
    ) -> list[Decision]:
        """Decide for each pending resident, using ``info`` and nothing else."""
        ...

    def belief_hazard(self, info: InformationSet) -> ArrivalTimeHazard:
        """The hazard field this policy believes in at ``info``'s time."""
        ...


@dataclass(frozen=True)
class DecisionTrace:
    """Per-resident record of what happened, belief side and truth side."""

    resident_id: str
    action: str
    reason: str
    decision_time_min: float | None
    belief_feasible: bool
    truth_feasible: bool
    truth_reason: str
    outcome_state: str
    self_evacuation_state: str
    travel_time_min: float
    responder_exposure_min: float
    truth_arrival_at_house_min: float
    threatened: bool
    n_wait_steps: int
    loss_components: LossComponents

    def loss(self, weights: LossWeights) -> float:
        return self.loss_components.value(weights)


@dataclass(frozen=True)
class PolicyResult:
    """The outcome of running one policy over one world."""

    policy_id: str
    world_id: int
    traces: tuple[DecisionTrace, ...]
    diagnostics: dict = field(default_factory=dict)

    def mean_loss(self, weights: LossWeights = LossWeights()) -> float:
        if not self.traces:
            return 0.0
        return sum(t.loss(weights) for t in self.traces) / len(self.traces)


def decision_times(horizon_min: float, interval_min: float = DECISION_INTERVAL_MIN):
    """Decision opportunities, from ``0`` up to (not past) the horizon."""
    t = 0.0
    out: list[float] = []
    while t <= horizon_min + 1e-9:
        out.append(round(t, 6))
        t += interval_min
    return out


def run_policy(
    world: ExperimentWorld,
    policy: Policy,
    weights: LossWeights = LossWeights(),
    adapter: PlaceholderDispatchAdapter | None = None,
    interval_min: float = DECISION_INTERVAL_MIN,
) -> PolicyResult:
    """Run one policy over one world and score it against hidden truth.

    The policy sees only information sets.  Every call into policy code happens
    inside :func:`~wildfireguardian_fv.info.truth_access_guard`, so an attempt
    to open a ``truth/`` artefact raises instead of quietly succeeding.

    Args:
        world: the hidden world.  Both policies in a pair get this same object.
        policy: any object satisfying :class:`Policy`.
        weights: loss weights.
        adapter: mission feasibility adapter; the internal placeholder by
            default.
        interval_min: decision cadence.

    Returns:
        A :class:`PolicyResult` with one :class:`DecisionTrace` per resident.
    """
    adapter = adapter or PlaceholderDispatchAdapter()
    truth = world.truth_hazard()
    threatened = world.threatened_residents()
    arrivals = world.resident_arrival_times_min()

    pending = tuple(r.resident_id for r in world.village.residents)
    committed: dict[str, tuple[float, MissionPlan | None, str, str]] = {}
    waits: dict[str, int] = {rid: 0 for rid in pending}
    last_reason: dict[str, str] = {rid: "NEVER_TRIGGERED" for rid in pending}
    n_info_sets = 0

    for s in decision_times(world.horizon_min, interval_min):
        if not pending:
            break
        info = build_information_set(world, s)
        n_info_sets += 1
        with truth_access_guard():
            decisions = policy.decide(info, pending, s)
        still_pending: list[str] = []
        for d in decisions:
            if d.action == "ACT_NOW":
                committed[d.resident_id] = (s, d.plan, d.reason, "ACT_NOW")
            elif d.action == "WAIT_FOR_FORECAST":
                waits[d.resident_id] += 1
                last_reason[d.resident_id] = d.reason
                still_pending.append(d.resident_id)
            else:
                last_reason[d.resident_id] = d.reason
                still_pending.append(d.resident_id)
        pending = tuple(still_pending)

    # Residents never actioned: recorded explicitly, never silently dropped,
    # and carrying the *last* reason the policy gave rather than a generic one
    # -- that reason is what FAILURE_ANALYSIS.md is built from.
    for rid in pending:
        committed[rid] = (None, None, last_reason.get(rid, "NEVER_TRIGGERED"),
                          "NO_ACTION")

    traces: list[DecisionTrace] = []
    for r in world.village.residents:
        s_dec, plan, reason, action = committed[r.resident_id]
        belief_feasible = plan is not None
        if plan is None:
            truth_outcome = MissionOutcome(feasible=False, reason=reason)
        else:
            truth_outcome = adapter.evaluate_plan(world.village, truth, plan)
        self_evac = adapter.self_evacuation_feasible(
            world.village,
            truth,
            r.resident_id,
            0.0 if s_dec is None else s_dec,
            world.horizon_min,
        )
        is_threatened = r.resident_id in threatened
        components = LossComponents(
            protection_failure=bool(is_threatened and not truth_outcome.feasible),
            unnecessary_dispatch=bool(plan is not None and not is_threatened),
            dispatched=bool(plan is not None),
            travel_time_min=(
                plan.travel_time_min if (plan is not None and truth_outcome.feasible)
                else (plan.travel_time_min if plan is not None else 0.0)
            ),
            responder_exposure_min=float(truth_outcome.responder_exposure_min),
        )
        traces.append(
            DecisionTrace(
                resident_id=r.resident_id,
                action=action,
                reason=reason,
                decision_time_min=s_dec,
                belief_feasible=belief_feasible,
                truth_feasible=bool(truth_outcome.feasible),
                truth_reason=truth_outcome.reason,
                outcome_state=(
                    "ROUTE_EVIDENCE_UNRESOLVED"
                    if action == "NO_ACTION"
                    and reason in ("NEVER_TRIGGERED", "NO_FIRE_EVIDENCE",
                                   "OUTSIDE_TRIGGER_BUFFER", "NO_PREDICTED_THREAT")
                    and not is_threatened
                    else classify_outcome(truth_outcome, self_evac)
                ),
                self_evacuation_state=(
                    "SELF_EVACUATION_FEASIBLE" if self_evac.feasible
                    else self_evac.reason
                ),
                travel_time_min=components.travel_time_min,
                responder_exposure_min=components.responder_exposure_min,
                truth_arrival_at_house_min=float(arrivals[r.resident_id]),
                threatened=is_threatened,
                n_wait_steps=int(waits.get(r.resident_id, 0)),
                loss_components=components,
            )
        )

    return PolicyResult(
        policy_id=policy.policy_id,
        world_id=world.world_id,
        traces=tuple(traces),
        diagnostics={
            "n_information_sets_built": n_info_sets,
            "n_dispatched": sum(1 for t in traces if t.loss_components.dispatched),
            "n_threatened": len(threatened),
            "adapter_id": adapter.adapter_id,
            "traversal_semantics": adapter.semantics,
        },
    )
