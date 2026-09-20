"""Baseline policies.

The primary baseline is a **strong tuned trigger/buffer** policy, not a straw
man.  It uses the same state estimator the forecast-aware policy uses, it
chooses between routes on current evidence, and its buffer is tuned by grid
search on the validation split only (``PROTOCOL.md`` section 9).

Making it weak would guarantee the headline result and destroy the experiment.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..missions.outcomes import FeasibilityState
from ..planner.estimate import estimate_fire_state, estimate_wind
from ..planner.forecast import Forecast
from ..planner.view import AvailableData
from .base import PolicyAction, PolicyContext


@dataclass(frozen=True)
class BaselineParams:
    """Tuned on the validation split, then frozen.

    Attributes:
        buffer_m: spatial buffer around the village and the planned route.
        time_buffer_min: how far ahead the wind term looks.
        wind_gain: metres of extra buffer per (m/s of wind x minute of lookahead).
    """

    buffer_m: float = 500.0
    time_buffer_min: float = 20.0
    wind_gain: float = 4.0

    def trigger_distance_m(self, wind_speed_ms: float) -> float:
        """Wind-conditioned persistence distance."""
        return float(
            self.buffer_m + self.wind_gain * max(0.0, wind_speed_ms) * self.time_buffer_min
        )

    def as_dict(self) -> dict:
        return {
            "buffer_m": self.buffer_m,
            "time_buffer_min": self.time_buffer_min,
            "wind_gain": self.wind_gain,
        }


def _route_min_distance(estimate, route, grid) -> float:
    """Smallest distance from the estimated fire edge to any cell of a route."""
    worst = float("inf")
    for edge in route.edges:
        rows, cols, _ = edge.sample_cells(grid)
        xs, ys = grid.ij_to_xy(rows, cols)
        distances = np.hypot(xs - estimate.centroid_x_m, ys - estimate.centroid_y_m)
        worst = min(worst, float(np.maximum(distances - estimate.radius_m, 0.0).min()))
    return worst


def _choose_route_on_evidence(estimate, context) -> str:
    """Pick the route currently furthest from the estimated fire.

    Ties break toward the shorter route.  This is what makes the baseline
    strong: it is not locked to one road.
    """
    network = context.view.geometry.network
    best_id, best_key = "", None
    for route in network.evacuation_routes:
        distance = _route_min_distance(estimate, route, context.view.grid)
        key = (-distance, route.length_m)
        if best_key is None or key < best_key:
            best_id, best_key = route.route_id, key
    return best_id


class TunedBufferBaseline:
    """Primary baseline: wind-conditioned trigger/buffer on observed fire state."""

    def __init__(self, params: BaselineParams | None = None) -> None:
        self.params = params or BaselineParams()
        self.policy_id = "baseline_tuned_buffer"

    def reset(self) -> None:
        return None

    def trigger(self, data: AvailableData, context: PolicyContext):
        """Return ``(fires, estimate, distance, threshold)``."""
        estimate = estimate_fire_state(data)
        if not estimate.valid:
            return False, estimate, float("inf"), float("nan")
        wind = estimate_wind(data)
        threshold = self.params.trigger_distance_m(wind.speed_ms if wind.valid else 0.0)

        village = context.view.geometry.village_xy_m
        d_village = estimate.distance_to(*village)
        route_id = _choose_route_on_evidence(estimate, context)
        d_route = _route_min_distance(
            estimate, context.view.geometry.network.route(route_id), context.view.grid
        )
        distance = min(d_village, d_route)
        return distance <= threshold, estimate, distance, threshold

    def decide(
        self, *, s_min: float, data: AvailableData, forecast: Forecast | None,
        context: PolicyContext,
    ) -> PolicyAction:
        fires, estimate, distance, threshold = self.trigger(data, context)
        if not fires:
            return PolicyAction(
                order=False,
                rationale=(
                    "no fire evidence"
                    if not estimate.valid
                    else f"nearest observed fire {distance:.0f} m > buffer {threshold:.0f} m"
                ),
            )
        return PolicyAction(
            order=True,
            route_id=_choose_route_on_evidence(estimate, context),
            rationale=f"observed fire {distance:.0f} m <= buffer {threshold:.0f} m",
            believed_state=FeasibilityState.ROUTE_EVIDENCE_UNRESOLVED,
        )


class FixedBufferBaseline(TunedBufferBaseline):
    """Secondary baseline: spatial buffer only, no wind term."""

    def __init__(self, buffer_m: float = 800.0) -> None:
        super().__init__(BaselineParams(buffer_m=buffer_m, wind_gain=0.0))
        self.policy_id = "baseline_fixed_buffer"


class WindConditionedBaseline(TunedBufferBaseline):
    """Secondary baseline: wind term only, minimal fixed buffer."""

    def __init__(self, wind_gain: float = 6.0, time_buffer_min: float = 20.0) -> None:
        super().__init__(
            BaselineParams(buffer_m=100.0, wind_gain=wind_gain, time_buffer_min=time_buffer_min)
        )
        self.policy_id = "baseline_wind_conditioned"


class FireBlindBaseline:
    """Secondary baseline: order at a fixed time, ignoring all observations."""

    def __init__(self, order_at_min: float = 60.0) -> None:
        self.order_at_min = float(order_at_min)
        self.policy_id = "baseline_fire_blind"

    def reset(self) -> None:
        return None

    def decide(
        self, *, s_min: float, data: AvailableData, forecast: Forecast | None,
        context: PolicyContext,
    ) -> PolicyAction:
        if s_min + 1e-9 < self.order_at_min:
            return PolicyAction(order=False, rationale="before the fixed order time")
        network = context.view.geometry.network
        shortest = min(network.evacuation_routes, key=lambda r: r.length_m)
        return PolicyAction(
            order=True,
            route_id=shortest.route_id,
            rationale=f"fixed order time {self.order_at_min:.0f} min reached",
        )


class OracleReference:
    """Upper bound only.  **Not an executable operational policy.**

    Chooses, with perfect knowledge of the hidden arrival field, the latest
    order time that still completes the mission.  It is reported as a bound on
    what any forecast could buy, never as something anyone could run.  It is
    evaluated outside the planner sandbox for exactly that reason.
    """

    policy_id = "oracle_reference"

    def __init__(self, truth_arrival_min, adapter, geometry, horizon_min: float) -> None:
        self.truth_arrival_min = truth_arrival_min
        self.adapter = adapter
        self.geometry = geometry
        self.horizon_min = float(horizon_min)

    def best_order_time(self, mission_kind, epochs) -> tuple[float | None, str]:
        """Latest epoch at which some route still completes the mission."""
        from ..missions.outcomes import MissionKind

        best_time, best_route = None, ""
        for s in epochs:
            for route in self.geometry.network.evacuation_routes:
                if mission_kind is MissionKind.SELF_EVACUATION:
                    result = self.adapter.evaluate_self_evacuation(
                        order_time_min=s, route=route,
                        arrival_time_min=self.truth_arrival_min,
                        grid=self.geometry.grid, horizon_min=self.horizon_min,
                    )
                else:
                    result = self.adapter.evaluate_assisted(
                        order_time_min=s, approach=self.geometry.network.approach_route,
                        route=route, arrival_time_min=self.truth_arrival_min,
                        grid=self.geometry.grid, horizon_min=self.horizon_min,
                    )
                if result.feasible:
                    best_time, best_route = float(s), route.route_id
        return best_time, best_route
