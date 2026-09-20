"""The decision loop, and the contract every policy satisfies.

A policy is asked, at each decision epoch, whether to order a protective action
now.  It sees ``D_s`` and, if it is forecast-aware, the newest forecast already
available.  It never sees hidden truth: the loop runs inside a planner sandbox
(``planner/sandbox.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from ..missions.dispatch import PlaceholderDispatchAdapter
from ..missions.outcomes import FeasibilityState, MissionKind
from ..planner.forecast import Forecast
from ..planner.sandbox import planner_sandbox
from ..planner.view import AvailableData, PlannerView

#: Decision epochs: every 10 minutes from 20 minutes after ignition.
DECISION_START_MIN = 20.0
DECISION_EPOCH_STEP_MIN = 10.0


class WaitSemantics(str, Enum):
    """How a policy behaves when its trigger fires.

    ``ACT_NOW`` is primary.  ``WAIT_FOR_FORECAST`` exists to make the cost of
    waiting explicit: waiting consumes real decision time and can destroy
    options, because the fire does not pause while the policy deliberates
    (``PROTOCOL.md`` section 4).
    """

    ACT_NOW = "ACT_NOW"
    WAIT_FOR_FORECAST = "WAIT_FOR_FORECAST"


def decision_epochs(horizon_min: float) -> list[float]:
    """The decision epochs for a world."""
    epochs: list[float] = []
    t = DECISION_START_MIN
    while t <= horizon_min + 1e-9:
        epochs.append(float(t))
        t += DECISION_EPOCH_STEP_MIN
    return epochs


@dataclass(frozen=True)
class PolicyContext:
    """Static things a policy may consult.  Contains no truth."""

    view: PlannerView
    adapter: PlaceholderDispatchAdapter
    mission_kind: MissionKind
    horizon_min: float
    epoch_step_min: float = DECISION_EPOCH_STEP_MIN


@dataclass(frozen=True)
class PolicyAction:
    """What a policy decided at one epoch."""

    order: bool
    route_id: str = ""
    rationale: str = ""
    believed_state: FeasibilityState = FeasibilityState.ROUTE_EVIDENCE_UNRESOLVED


@dataclass
class PolicyDecision:
    """The outcome of running a policy over a world."""

    policy_id: str
    mission_kind: MissionKind
    order_time_min: float | None
    route_id: str
    rationale: str
    believed_state: FeasibilityState
    wait_semantics: WaitSemantics
    n_epochs_evaluated: int
    forecast_used: bool
    forecast_issue_time_min: float | None = None
    log: list[dict] = field(default_factory=list)

    @property
    def ordered(self) -> bool:
        return self.order_time_min is not None


class Policy(Protocol):
    """Contract for a decision policy."""

    policy_id: str

    def reset(self) -> None:
        ...

    def decide(
        self,
        *,
        s_min: float,
        data: AvailableData,
        forecast: Forecast | None,
        context: PolicyContext,
    ) -> PolicyAction:
        ...


def run_policy(
    policy: Policy,
    *,
    context: PolicyContext,
    forecast_at: Callable[[float], Forecast | None] | None = None,
    wait_semantics: WaitSemantics = WaitSemantics.ACT_NOW,
) -> PolicyDecision:
    """Run a policy across the decision epochs of one world.

    Args:
        policy: the policy to run.
        context: static planner-side context.
        forecast_at: returns the newest forecast **usable** at a given epoch, or
            ``None``.  Omitted for policies that do not use forecasts.
        wait_semantics: ``ACT_NOW`` orders at the epoch the trigger fires;
            ``WAIT_FOR_FORECAST`` holds until the next forecast arrives and
            re-evaluates then, losing that time.

    Returns:
        A :class:`PolicyDecision`.  The whole loop runs inside a planner
        sandbox, so any attempt to read hidden truth raises.
    """
    policy.reset()
    epochs = decision_epochs(context.horizon_min)
    log: list[dict] = []
    held_since: float | None = None

    with planner_sandbox():
        for index, s in enumerate(epochs):
            data = context.view.at(s)
            forecast = forecast_at(s) if forecast_at is not None else None
            if forecast is not None and not forecast.usable_at(s):
                raise AssertionError(
                    f"forecast issued at {forecast.issue_time_min} is available at "
                    f"{forecast.availability_time_min}, after the decision "
                    f"epoch {s} (PROTOCOL.md section 13)"
                )
            action = policy.decide(s_min=s, data=data, forecast=forecast, context=context)
            log.append(
                {
                    "epoch_min": s,
                    "n_detections": data.n_detections(),
                    "forecast": None if forecast is None else forecast.issue_time_min,
                    "order": action.order,
                    "rationale": action.rationale,
                }
            )

            if not action.order:
                held_since = None
                continue

            if wait_semantics is WaitSemantics.WAIT_FOR_FORECAST:
                # Waiting is not free: hold until a *newer* forecast arrives,
                # then re-evaluate.  The fire keeps moving meanwhile.
                if held_since is None:
                    held_since = s
                    newer = (
                        forecast_at(s + context.epoch_step_min)
                        if forecast_at is not None
                        else None
                    )
                    arrived = newer is not None and (
                        forecast is None
                        or newer.issue_time_min > forecast.issue_time_min
                    )
                    if not arrived:
                        log[-1]["rationale"] += " | waiting for a newer forecast"
                        continue
                    log[-1]["rationale"] += " | waited one epoch for a newer forecast"

            return PolicyDecision(
                policy_id=policy.policy_id,
                mission_kind=context.mission_kind,
                order_time_min=float(s),
                route_id=action.route_id,
                rationale=action.rationale,
                believed_state=action.believed_state,
                wait_semantics=wait_semantics,
                n_epochs_evaluated=index + 1,
                forecast_used=forecast is not None,
                forecast_issue_time_min=None if forecast is None else forecast.issue_time_min,
                log=log,
            )

    return PolicyDecision(
        policy_id=policy.policy_id,
        mission_kind=context.mission_kind,
        order_time_min=None,
        route_id="",
        rationale="never triggered",
        believed_state=FeasibilityState.NO_FEASIBLE_MISSION_FOUND,
        wait_semantics=wait_semantics,
        n_epochs_evaluated=len(epochs),
        forecast_used=False,
        log=log,
    )
