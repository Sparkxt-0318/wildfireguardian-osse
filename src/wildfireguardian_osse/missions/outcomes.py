"""Outcome vocabulary for protective missions.

The word "safe" does not appear, by protocol: a mission is feasible or not, and
self-evacuation and assisted evacuation are separate capabilities.  The
inference "no self-evacuation route therefore rescue required" is never made
(``experiments/forecast_value_mve/PROTOCOL.md`` section 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MissionKind(str, Enum):
    """The two protective actions, evaluated in parallel and never conflated."""

    SELF_EVACUATION = "self_evacuation"
    ASSISTED_EVACUATION = "assisted_evacuation"


class FeasibilityState(str, Enum):
    """Assessment of what protective action is possible.

    ``ROUTE_EVIDENCE_UNRESOLVED`` is a **planner-side** state only: it means the
    available evidence does not determine the answer.  Evaluated against hidden
    truth the answer is always determined, so the evaluator never returns it.
    """

    SELF_EVACUATION_FEASIBLE = "SELF_EVACUATION_FEASIBLE"
    ASSISTANCE_FEASIBLE = "ASSISTANCE_FEASIBLE"
    BOTH_FEASIBLE = "BOTH_FEASIBLE"
    ROUTE_EVIDENCE_UNRESOLVED = "ROUTE_EVIDENCE_UNRESOLVED"
    NO_FEASIBLE_MISSION_FOUND = "NO_FEASIBLE_MISSION_FOUND"


class FailureReason(str, Enum):
    """Why a mission did not complete."""

    NONE = "none"
    NOT_ORDERED = "not_ordered"
    ROUTE_CUT_EN_ROUTE = "route_cut_en_route"
    ROUTE_ALREADY_BURNED = "route_already_burned"
    VILLAGE_BURNED_BEFORE_PICKUP = "village_burned_before_pickup"
    NO_ROUTE_AVAILABLE = "no_route_available"
    HORIZON_EXCEEDED = "horizon_exceeded"


@dataclass(frozen=True)
class MissionResult:
    """Outcome of one mission replayed against an arrival-time field.

    The same structure is produced whether the field is hidden truth (the
    evaluator) or a forecast (the planner's belief), which is what makes the
    two directly comparable.
    """

    kind: MissionKind
    feasible: bool
    order_time_min: float
    start_time_min: float
    end_time_min: float
    travel_time_min: float
    responder_exposure_min: float
    route_id: str
    failure_reason: FailureReason = FailureReason.NONE
    blocked_edge: str = ""
    blocked_at_min: float = float("nan")

    @property
    def duration_min(self) -> float:
        return self.end_time_min - self.order_time_min
