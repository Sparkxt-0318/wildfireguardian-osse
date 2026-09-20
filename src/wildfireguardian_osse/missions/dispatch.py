"""The assisted-dispatch adapter contract, and a minimal placeholder.

``wildfireguardian-assisted-dispatch`` owns mission feasibility semantics.  It
is not available to this run, and its full ``base -> resident -> pickup ->
destination`` logic is deliberately **not** reimplemented here.  What this
module provides is:

* :class:`DispatchAdapter` -- the contract the real package will satisfy;
* :class:`PlaceholderDispatchAdapter` -- a minimal, clearly-labelled stand-in.

The placeholder implements exactly three semantics, chosen because the
experiment depends on them:

1. **Full edge traversal interval.**  A vehicle occupies each cell of an edge
   at a known time.  The edge is passable only if no cell of it is *in its
   blockage window* when the vehicle occupies that cell -- not merely "the edge
   is unburned at entry".
2. **Pickup duration.**  Assisted evacuation dwells at the village, and the
   fire may arrive during the dwell.
3. **Coherent scenarios.**  One arrival-time field drives every leg of every
   mission, so legs cannot contradict each other.

**A road is blocked while the front is at it, not forever.**  A cell blocks a
vehicle during ``[arrival, arrival + road_blockage_duration_min]`` and is
passable afterwards.  This is what produces **non-monotone feasible dispatch
windows**: waiting can close a window and can also *reopen* one, because a
later start may let the front cross a segment before the vehicle reaches it.

Treating a burned cell as permanently impassable -- the first implementation
here -- makes feasibility monotonically decreasing in the order time, which
makes "act as early as possible" trivially optimal and destroys the very
property the brief asks these semantics to govern.  The inconsistency was
caught by ``tests/test_missions.py``, which now demonstrates a window closing
and reopening.

Everything else the real package models -- fleets, resident heterogeneity,
multi-stop routing, re-tasking -- is **absent**, and listed in
``experiments/forecast_value_mve/reports/LIMITATIONS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from ..landscape.grid import Grid
from .network import Route
from .outcomes import FailureReason, MissionKind, MissionResult

#: Identifier recorded in every run manifest so results computed against the
#: placeholder can never be mistaken for results against the real package.
DISPATCH_SEMANTICS_ID = "placeholder-dispatch-0.1.0"


@runtime_checkable
class DispatchAdapter(Protocol):
    """Contract that ``wildfireguardian-assisted-dispatch`` will satisfy.

    Both methods replay a mission against an **arrival-time field**: hidden
    truth when the evaluator calls them, a forecast when the planner does.
    Nothing in the contract knows which it was given, which is precisely what
    makes planner belief and evaluator outcome comparable.
    """

    semantics_id: str

    def evaluate_self_evacuation(
        self, *, order_time_min: float, route: Route, arrival_time_min: np.ndarray,
        grid: Grid, horizon_min: float,
    ) -> MissionResult:
        ...

    def evaluate_assisted(
        self, *, order_time_min: float, approach: Route, route: Route,
        arrival_time_min: np.ndarray, grid: Grid, horizon_min: float,
    ) -> MissionResult:
        ...


@dataclass(frozen=True)
class PlaceholderDispatchAdapter:
    """Minimal stand-in for the real dispatch package.  Clearly labelled."""

    semantics_id: str = DISPATCH_SEMANTICS_ID
    speed_m_per_min: float = 450.0          # ~27 km/h on rural roads
    self_evac_prep_min: float = 10.0        # residents mobilise
    responder_dispatch_min: float = 5.0     # responder leaves base
    pickup_duration_min: float = 12.0       # dwell at the village
    exposure_radius_m: float = 400.0        # responder exposure counted within
    exposure_sample_min: float = 1.0
    #: How long a cell stays impassable after the fire reaches it.  A declared
    #: placeholder parameter; the real dispatch package owns this semantics.
    road_blockage_duration_min: float = 60.0

    # -- edge traversal --------------------------------------------------
    def traverse(
        self,
        route: Route,
        start_min: float,
        arrival_time_min: np.ndarray,
        grid: Grid,
    ) -> tuple[bool, float, str, float]:
        """Attempt to traverse ``route`` starting at ``start_min``.

        Returns:
            ``(completed, end_time_min, blocked_edge_id, blocked_at_min)``.

        A cell blocks the vehicle while it is inside its blockage window,
        ``[arrival, arrival + road_blockage_duration_min]``.  This is the
        full-traversal-interval rule: a segment entered before the fire but
        long enough for the fire to cross it mid-way is **not** passable, while
        a segment the front crossed long ago is passable again.
        """
        t = float(start_min)
        for edge in route.edges:
            rows, cols, fractions = edge.sample_cells(grid)
            edge_time = edge.length_m / self.speed_m_per_min
            occupancy = t + fractions * edge_time
            arrivals = arrival_time_min[rows, cols]
            blocked = (arrivals <= occupancy) & (
                occupancy <= arrivals + self.road_blockage_duration_min
            )
            if np.any(blocked):
                k = int(np.argmax(blocked))
                return False, float(occupancy[k]), edge.edge_id, float(arrivals[k])
            t += edge_time
        return True, t, "", float("nan")

    # -- exposure --------------------------------------------------------
    def exposure_minutes(
        self,
        route: Route,
        start_min: float,
        end_min: float,
        arrival_time_min: np.ndarray,
        grid: Grid,
    ) -> float:
        """Minutes spent within ``exposure_radius_m`` of already-burning ground."""
        if not np.isfinite(start_min) or end_min <= start_min:
            return 0.0
        total_time = sum(e.length_m for e in route.edges) / self.speed_m_per_min
        if total_time <= 0:
            return 0.0
        radius_cells = max(1, int(np.ceil(self.exposure_radius_m / grid.cell_size_m)))
        exposed = 0.0
        n_steps = max(1, int(np.ceil((end_min - start_min) / self.exposure_sample_min)))
        for step in range(n_steps):
            t = start_min + step * self.exposure_sample_min
            travelled = (t - start_min) * self.speed_m_per_min
            x, y = _point_along(route, travelled)
            i, j = grid.xy_to_ij(x, y)
            i0, i1 = max(0, i - radius_cells), min(grid.ny, i + radius_cells + 1)
            j0, j1 = max(0, j - radius_cells), min(grid.nx, j + radius_cells + 1)
            window = arrival_time_min[i0:i1, j0:j1]
            if np.any(window <= t):
                exposed += self.exposure_sample_min
        return float(exposed)

    # -- missions --------------------------------------------------------
    def evaluate_self_evacuation(
        self, *, order_time_min: float, route: Route, arrival_time_min: np.ndarray,
        grid: Grid, horizon_min: float,
    ) -> MissionResult:
        start = order_time_min + self.self_evac_prep_min
        completed, end, blocked_edge, blocked_at = self.traverse(
            route, start, arrival_time_min, grid
        )
        travel = (end - start) if completed else float("nan")
        reason = FailureReason.NONE
        if not completed:
            reason = (
                FailureReason.ROUTE_ALREADY_BURNED
                if blocked_at <= start
                else FailureReason.ROUTE_CUT_EN_ROUTE
            )
        elif end > horizon_min:
            completed, reason = False, FailureReason.HORIZON_EXCEEDED
        return MissionResult(
            kind=MissionKind.SELF_EVACUATION,
            feasible=completed,
            order_time_min=float(order_time_min),
            start_time_min=float(start),
            end_time_min=float(end),
            travel_time_min=float(travel) if completed else float("nan"),
            responder_exposure_min=0.0,   # residents are not responders
            route_id=route.route_id,
            failure_reason=reason,
            blocked_edge=blocked_edge,
            blocked_at_min=blocked_at,
        )

    def evaluate_assisted(
        self, *, order_time_min: float, approach: Route, route: Route,
        arrival_time_min: np.ndarray, grid: Grid, horizon_min: float,
    ) -> MissionResult:
        depart = order_time_min + self.responder_dispatch_min
        reached, at_village, blocked_edge, blocked_at = self.traverse(
            approach, depart, arrival_time_min, grid
        )
        exposure = self.exposure_minutes(
            approach, depart, at_village if reached else blocked_at, arrival_time_min, grid
        )
        if not reached:
            return MissionResult(
                kind=MissionKind.ASSISTED_EVACUATION, feasible=False,
                order_time_min=float(order_time_min), start_time_min=float(depart),
                end_time_min=float(blocked_at), travel_time_min=float("nan"),
                responder_exposure_min=exposure, route_id=route.route_id,
                failure_reason=FailureReason.ROUTE_CUT_EN_ROUTE,
                blocked_edge=blocked_edge, blocked_at_min=blocked_at,
            )

        # The dwell at the village: the fire may arrive during the pickup.
        village_end = approach.edges[-1]
        vi, vj = grid.xy_to_ij(village_end.x1_m, village_end.y1_m)
        pickup_end = at_village + self.pickup_duration_min
        village_arrival = float(arrival_time_min[vi, vj])
        # The fire arriving *during* the dwell loses the mission; a village the
        # front crossed long before the responder got there is not a live
        # hazard to the pickup.
        if (
            village_arrival <= pickup_end
            and at_village <= village_arrival + self.road_blockage_duration_min
        ):
            return MissionResult(
                kind=MissionKind.ASSISTED_EVACUATION, feasible=False,
                order_time_min=float(order_time_min), start_time_min=float(depart),
                end_time_min=village_arrival, travel_time_min=float("nan"),
                responder_exposure_min=exposure + self.pickup_duration_min,
                route_id=route.route_id,
                failure_reason=FailureReason.VILLAGE_BURNED_BEFORE_PICKUP,
                blocked_edge="village_dwell",
                blocked_at_min=village_arrival,
            )

        completed, end, blocked_edge, blocked_at = self.traverse(
            route, pickup_end, arrival_time_min, grid
        )
        exposure += self.pickup_duration_min
        exposure += self.exposure_minutes(
            route, pickup_end, end if completed else blocked_at, arrival_time_min, grid
        )
        reason = FailureReason.NONE
        if not completed:
            reason = (
                FailureReason.ROUTE_ALREADY_BURNED
                if blocked_at <= pickup_end
                else FailureReason.ROUTE_CUT_EN_ROUTE
            )
        elif end > horizon_min:
            completed, reason = False, FailureReason.HORIZON_EXCEEDED
        return MissionResult(
            kind=MissionKind.ASSISTED_EVACUATION,
            feasible=completed,
            order_time_min=float(order_time_min),
            start_time_min=float(depart),
            end_time_min=float(end),
            travel_time_min=float(end - depart) if completed else float("nan"),
            responder_exposure_min=float(exposure),
            route_id=route.route_id,
            failure_reason=reason,
            blocked_edge=blocked_edge,
            blocked_at_min=blocked_at,
        )


def _point_along(route: Route, distance_m: float) -> tuple[float, float]:
    """Position ``distance_m`` along a route, clamped to its ends."""
    remaining = max(0.0, float(distance_m))
    for edge in route.edges:
        if remaining <= edge.length_m or edge is route.edges[-1]:
            f = 0.0 if edge.length_m <= 0 else min(1.0, remaining / edge.length_m)
            return (
                edge.x0_m + (edge.x1_m - edge.x0_m) * f,
                edge.y0_m + (edge.y1_m - edge.y0_m) * f,
            )
        remaining -= edge.length_m
    last = route.edges[-1]
    return (last.x1_m, last.y1_m)
