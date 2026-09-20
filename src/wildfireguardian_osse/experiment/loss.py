"""The loss function, declared before the final run.

```
J(a, omega) = 1.00 * mission_failed
            + 0.50 * unnecessary_action
            + 0.30 * excess_lead_hours
            + 0.01 * responder_exposure_min
            + 0.001 * travel_time_min
```

No mortality term and no lives-saved term: neither is defensible from this
model, and both would make every downstream number a claim about human
outcomes that this repository cannot support (``PROTOCOL.md`` section 8).

Failure dominates, and the remaining terms are what make acting too early
costly.  Without them a policy that evacuates at the first epoch of every world
would be optimal and the experiment would measure nothing.

**Why these weights and not the first set tried.**  The first declared weights
(0.20 / 0.05) were measured on the development split and found *degenerate*:
evacuating four hours early cost about 0.06 against a failure cost of 1.0, so
"always order at the first epoch" was near-optimal and the tuned baseline came
within 0.01 of the oracle in every world.  An experiment whose baseline already
matches the oracle cannot discriminate between forecasts, and could not express
the "crude but timely" benchmark at all.  The weights were therefore rebalanced
**once**, on the argument that a four-hour-premature village evacuation is
roughly as costly as one failed mission -- not on any observed ``Delta J``, and
not iterated toward a preferred sign (``PROTOCOL.md`` sections 8 and 14, and
``docs/DECISIONS.md#d-017``).

The weights are a **declared modelling choice**, stamped into every record as
``loss_version``.  Sensitivity analysis over them is future work, and is the
first thing a sceptical reader should ask for.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ..landscape.grid import Grid
from ..missions.dispatch import PlaceholderDispatchAdapter
from ..missions.outcomes import FailureReason, MissionKind, MissionResult
from ..missions.village import WorldGeometry
from ..planner.sandbox import assert_evaluator_context
from ..policies.base import PolicyDecision

LOSS_VERSION = "mve-loss-1.1.0"

W_MISSION_FAILED = 1.00
W_UNNECESSARY_ACTION = 0.50
W_EXCESS_LEAD_PER_HOUR = 0.30
W_RESPONDER_EXPOSURE_PER_MIN = 0.01
W_TRAVEL_PER_MIN = 0.001

#: Fire within this distance of the village counts as having threatened it.
THREAT_RADIUS_M = 300.0
#: Lead time beyond this allowance is charged as premature disruption.
LEAD_ALLOWANCE_MIN = 30.0


@dataclass(frozen=True)
class LossBreakdown:
    """Every term of ``J``, kept separate so results stay interpretable."""

    loss: float
    mission_failed: int
    unnecessary_action: int
    excess_lead_hours: float
    responder_exposure_min: float
    travel_time_min: float
    ordered: int
    order_time_min: float
    threatened: int
    threat_time_min: float
    failure_reason: str
    route_id: str
    mission_kind: str

    def as_dict(self) -> dict:
        return asdict(self)


def threat_time(
    truth_arrival_min: np.ndarray, grid: Grid, geometry: WorldGeometry
) -> float:
    """First minute the fire comes within ``THREAT_RADIUS_M`` of the village."""
    assert_evaluator_context("threat time (reads hidden truth)")
    X, Y = grid.cell_centres()
    near = np.hypot(X - geometry.village_xy_m[0], Y - geometry.village_xy_m[1]) <= THREAT_RADIUS_M
    times = truth_arrival_min[near]
    finite = times[np.isfinite(times)]
    return float(finite.min()) if finite.size else float("inf")


def compute_loss(
    *,
    ordered: bool,
    order_time_min: float,
    result: MissionResult | None,
    threat_time_min: float,
    horizon_min: float,
    mission_kind: MissionKind,
    route_id: str,
) -> LossBreakdown:
    """Score one decision against the hidden world."""
    threatened = bool(np.isfinite(threat_time_min) and threat_time_min <= horizon_min)

    if not ordered:
        failed = int(threatened)
        return LossBreakdown(
            loss=W_MISSION_FAILED * failed,
            mission_failed=failed,
            unnecessary_action=0,
            excess_lead_hours=0.0,
            responder_exposure_min=0.0,
            travel_time_min=0.0,
            ordered=0,
            order_time_min=float("nan"),
            threatened=int(threatened),
            threat_time_min=float(threat_time_min),
            failure_reason=(
                FailureReason.NOT_ORDERED.value if threatened else FailureReason.NONE.value
            ),
            route_id="",
            mission_kind=mission_kind.value,
        )

    assert result is not None, "an ordered action must have a mission result"
    failed = int(not result.feasible)
    unnecessary = int(not threatened)
    if threatened:
        lead_min = max(0.0, threat_time_min - order_time_min)
        excess_hours = max(0.0, (lead_min - LEAD_ALLOWANCE_MIN) / 60.0)
    else:
        # Charged as an unnecessary action instead; not double-counted.
        excess_hours = 0.0

    travel = float(result.travel_time_min) if result.feasible else 0.0
    exposure = float(result.responder_exposure_min)
    loss = (
        W_MISSION_FAILED * failed
        + W_UNNECESSARY_ACTION * unnecessary
        + W_EXCESS_LEAD_PER_HOUR * excess_hours
        + W_RESPONDER_EXPOSURE_PER_MIN * exposure
        + W_TRAVEL_PER_MIN * travel
    )
    return LossBreakdown(
        loss=float(loss),
        mission_failed=failed,
        unnecessary_action=unnecessary,
        excess_lead_hours=float(excess_hours),
        responder_exposure_min=exposure,
        travel_time_min=travel,
        ordered=1,
        order_time_min=float(order_time_min),
        threatened=int(threatened),
        threat_time_min=float(threat_time_min),
        failure_reason=result.failure_reason.value,
        route_id=result.route_id,
        mission_kind=mission_kind.value,
    )


def evaluate_decision(
    *,
    decision: PolicyDecision,
    truth_arrival_min: np.ndarray,
    geometry: WorldGeometry,
    adapter: PlaceholderDispatchAdapter,
    horizon_min: float,
    threat_time_min: float,
) -> tuple[LossBreakdown, MissionResult | None]:
    """Replay a decision against hidden truth and score it.

    Evaluator-only: this is where the hidden arrival field is finally used.
    """
    assert_evaluator_context("decision evaluation (reads hidden truth)")

    if not decision.ordered:
        return (
            compute_loss(
                ordered=False, order_time_min=float("nan"), result=None,
                threat_time_min=threat_time_min, horizon_min=horizon_min,
                mission_kind=decision.mission_kind, route_id="",
            ),
            None,
        )

    network = geometry.network
    route = network.route(decision.route_id) if decision.route_id else min(
        network.evacuation_routes, key=lambda r: r.length_m
    )
    if decision.mission_kind is MissionKind.SELF_EVACUATION:
        result = adapter.evaluate_self_evacuation(
            order_time_min=decision.order_time_min, route=route,
            arrival_time_min=truth_arrival_min, grid=geometry.grid,
            horizon_min=horizon_min,
        )
    else:
        result = adapter.evaluate_assisted(
            order_time_min=decision.order_time_min, approach=network.approach_route,
            route=route, arrival_time_min=truth_arrival_min, grid=geometry.grid,
            horizon_min=horizon_min,
        )
    breakdown = compute_loss(
        ordered=True, order_time_min=float(decision.order_time_min), result=result,
        threat_time_min=threat_time_min, horizon_min=horizon_min,
        mission_kind=decision.mission_kind, route_id=result.route_id,
    )
    return breakdown, result
