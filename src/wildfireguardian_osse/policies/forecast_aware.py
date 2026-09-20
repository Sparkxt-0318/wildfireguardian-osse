"""The primary forecast-aware policy.

One policy, with semantics held fixed across every error and latency sweep --
which is what makes ``Delta J(theta)`` interpretable.  Fifteen variants are not
compared (``PROTOCOL.md`` section 9).

The rule is simple and deliberately not hedged with a baseline floor: **order
when the forecast says that waiting a safety margin longer would lose the
mission.**  Without a floor the forecast can make the policy act later as well
as earlier, so a wrong forecast can genuinely do harm.  With a floor it could
only ever act earlier, ``Delta J`` could only move one way, and "forecast harm"
would be unreachable by construction.

``safety_margin_min`` is the one tuned parameter, and it exists for a reason
found by measurement, not by taste.  With a zero margin the policy acts at the
*exact* feasibility boundary the forecast draws, which is the most
error-sensitive point available: any displacement of the predicted front moves
the boundary, and the policy walks straight off it.  Benchmark validation on
the development split showed that a zero-margin policy lost to the tuned
baseline at every non-zero error level, so ``CRUDE_BUT_TIMELY`` could not be
expressed at all.

The margin is tuned on the **validation** split, over the whole condition grid
at once rather than per condition, and then frozen -- exactly as the baseline
buffer is.  Tuning the baseline while leaving the forecast-aware policy untuned
would be an asymmetry in the baseline's favour, and the protocol's requirement
is a *fair* comparison, not a flattering one (``PROTOCOL.md`` section 9).
"""

from __future__ import annotations

import numpy as np

from ..missions.outcomes import FeasibilityState, MissionKind
from ..planner.estimate import estimate_fire_state
from ..planner.forecast import Forecast
from ..planner.view import AvailableData
from .base import PolicyAction, PolicyContext
from .baseline import BaselineParams, TunedBufferBaseline


class ForecastAwareFeasibilityPolicy:
    """Act when the forecast says waiting would lose the mission."""

    def __init__(
        self,
        fallback_params: BaselineParams | None = None,
        safety_margin_min: float = 20.0,
    ) -> None:
        self.policy_id = "forecast_aware_feasibility"
        self.safety_margin_min = float(safety_margin_min)
        # Used only when no forecast exists at all (early epochs, or an
        # independent model with too little data to issue one).
        self._fallback = TunedBufferBaseline(fallback_params)

    def reset(self) -> None:
        self._fallback.reset()

    # -- feasibility under a belief field --------------------------------
    def _best_route(
        self, order_time_min: float, field: np.ndarray, context: PolicyContext
    ) -> tuple[bool, str]:
        """Shortest route that the belief field says completes the mission."""
        network = context.view.geometry.network
        feasible: list[tuple[float, str]] = []
        for route in sorted(network.evacuation_routes, key=lambda r: r.length_m):
            if context.mission_kind is MissionKind.SELF_EVACUATION:
                result = context.adapter.evaluate_self_evacuation(
                    order_time_min=order_time_min, route=route,
                    arrival_time_min=field, grid=context.view.grid,
                    horizon_min=context.horizon_min,
                )
            else:
                result = context.adapter.evaluate_assisted(
                    order_time_min=order_time_min,
                    approach=network.approach_route, route=route,
                    arrival_time_min=field, grid=context.view.grid,
                    horizon_min=context.horizon_min,
                )
            if result.feasible:
                feasible.append((route.length_m, route.route_id))
        if not feasible:
            return False, ""
        return True, min(feasible)[1]

    def _village_threatened(self, field: np.ndarray, context: PolicyContext) -> bool:
        i, j = context.view.grid.xy_to_ij(*context.view.geometry.village_xy_m)
        return bool(np.isfinite(field[i, j]))

    # -- decision --------------------------------------------------------
    def decide(
        self, *, s_min: float, data: AvailableData, forecast: Forecast | None,
        context: PolicyContext,
    ) -> PolicyAction:
        if forecast is None:
            action = self._fallback.decide(
                s_min=s_min, data=data, forecast=None, context=context
            )
            return PolicyAction(
                order=action.order,
                route_id=action.route_id,
                rationale=f"no forecast available; fell back to buffer trigger ({action.rationale})",
                believed_state=FeasibilityState.ROUTE_EVIDENCE_UNRESOLVED,
            )

        field = forecast.arrival_time_min
        lookahead = max(context.epoch_step_min, self.safety_margin_min)
        feasible_now, route_now = self._best_route(s_min, field, context)
        feasible_next, _ = self._best_route(s_min + lookahead, field, context)
        threatened = self._village_threatened(field, context)

        if feasible_now and not feasible_next:
            return PolicyAction(
                order=True, route_id=route_now,
                rationale=(
                    f"forecast: feasible now, not after a {lookahead:.0f} min "
                    "safety margin"
                ),
                believed_state=(
                    FeasibilityState.SELF_EVACUATION_FEASIBLE
                    if context.mission_kind is MissionKind.SELF_EVACUATION
                    else FeasibilityState.ASSISTANCE_FEASIBLE
                ),
            )
        if not feasible_now:
            if threatened:
                network = context.view.geometry.network
                fallback_route = min(
                    network.evacuation_routes, key=lambda r: r.length_m
                ).route_id
                return PolicyAction(
                    order=True, route_id=fallback_route,
                    rationale="forecast: no feasible route, village threatened; acting anyway",
                    believed_state=FeasibilityState.NO_FEASIBLE_MISSION_FOUND,
                )
            estimate = estimate_fire_state(data)
            return PolicyAction(
                order=False,
                rationale=(
                    "forecast: infeasible but village not predicted to be reached"
                    + ("" if estimate.valid else "; no fire evidence either")
                ),
                believed_state=FeasibilityState.ROUTE_EVIDENCE_UNRESOLVED,
            )
        return PolicyAction(
            order=False,
            rationale=(
                f"forecast: still feasible after a {lookahead:.0f} min margin; waiting"
            ),
            believed_state=(
                FeasibilityState.SELF_EVACUATION_FEASIBLE
                if context.mission_kind is MissionKind.SELF_EVACUATION
                else FeasibilityState.ASSISTANCE_FEASIBLE
            ),
        )
