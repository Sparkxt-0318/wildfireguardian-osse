"""Mission feasibility: the adapter contract, and a temporary internal placeholder.

``wildfireguardian-assisted-dispatch`` is the intended source of these
semantics.  Direct package integration is out of reach for this first run
(``docs/DECISIONS.md#d-001`` forbids importing another WildfireGuardian
repository into the laboratory, and the assisted-dispatch package is not
vendored here), so this module does two things:

1. defines the **adapter contract** -- the protocol an external dispatch
   package must satisfy to replace this file (:class:`MissionFeasibilityAdapter`);
2. provides a minimal internal placeholder implementing it, labelled
   ``INTERNAL_PLACEHOLDER_V1`` in every record it produces.

The placeholder is not a reimplementation of assisted dispatch.  It carries
exactly the four semantics the experiment depends on and nothing else:

* ``base -> resident -> destination`` mission shape;
* **full edge traversal interval** hazard semantics;
* an explicit pickup duration at the resident;
* one hazard field drives both belief-side and truth-side evaluation, so a
  scenario is *coherent*: the planner's feasibility question and the
  evaluator's feasibility question differ only in which field answers it.

See ``docs/DISPATCH_ADAPTER.md``.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from .village import RoadEdge, Village

#: Declared traversal semantics.  ``FULL_INTERVAL`` is the contract default and
#: the conservative one: an edge is unusable if any corridor point burns at any
#: time during the traversal, even behind the vehicle.
TRAVERSAL_SEMANTICS = ("FULL_INTERVAL", "POINT_IN_TIME")

#: Outcome vocabulary.  Deliberately excludes the word "safe"
#: (PROTOCOL.md section 6).
OUTCOME_STATES = (
    "SELF_EVACUATION_FEASIBLE",
    "ASSISTANCE_FEASIBLE",
    "BOTH_FEASIBLE",
    "ROUTE_EVIDENCE_UNRESOLVED",
    "NO_FEASIBLE_MISSION_FOUND",
)

#: Self-evacuation travel speed, metres per minute.  ``ASSUMED``: slower than a
#: responder vehicle, representing an elderly resident's own vehicle on the
#: same roads.
SELF_EVAC_SPEED_M_PER_MIN = 250.0


@dataclass(frozen=True)
class ArrivalTimeHazard:
    """A raster of fire arrival times, in minutes since ``t0``.

    The *same* class wraps hidden truth (for evaluation) and a forecast (for
    planning).  Which one a caller holds is a property of the caller, never of
    this object, which is why feasibility semantics cannot silently diverge
    between belief and outcome.
    """

    arrival_time_min: np.ndarray  # shape (ny, nx); +inf where never burned
    cell_size_m: float
    source: str  # "HIDDEN_TRUTH" or a forecast id -- recorded, never inspected

    def arrival_at(self, xy: np.ndarray) -> np.ndarray:
        """Arrival time at each ``(x_m, y_m)`` point; ``+inf`` outside the fire."""
        pts = np.atleast_2d(np.asarray(xy, dtype=float))
        ny, nx = self.arrival_time_min.shape
        j = np.clip((pts[:, 0] / self.cell_size_m).astype(int), 0, nx - 1)
        i = np.clip((pts[:, 1] / self.cell_size_m).astype(int), 0, ny - 1)
        return self.arrival_time_min[i, j]

    def min_arrival_on_edge(self, edge: RoadEdge) -> float:
        return float(np.min(self.arrival_at(np.asarray(edge.sample_xy_m))))


@dataclass(frozen=True)
class Leg:
    """One traversed edge with the interval the vehicle occupied it."""

    edge_id: str
    t_enter_min: float
    t_exit_min: float


@dataclass(frozen=True)
class MissionPlan:
    """A concrete plan: which resident, dispatched when, by which route."""

    resident_id: str
    dispatch_time_min: float
    outbound: tuple[Leg, ...]
    inbound: tuple[Leg, ...]
    destination_node: str
    pickup_start_min: float
    pickup_end_min: float
    completion_time_min: float

    @property
    def travel_time_min(self) -> float:
        return self.completion_time_min - self.dispatch_time_min

    def all_legs(self) -> tuple[Leg, ...]:
        return self.outbound + self.inbound


@dataclass(frozen=True)
class MissionOutcome:
    """The result of evaluating a plan against one hazard field."""

    feasible: bool
    reason: str
    plan: MissionPlan | None = None
    blocked_edge_id: str | None = None
    responder_exposure_min: float = 0.0
    adapter_id: str = "INTERNAL_PLACEHOLDER_V1"
    extras: dict = field(default_factory=dict)


@runtime_checkable
class MissionFeasibilityAdapter(Protocol):
    """Contract an external dispatch package must satisfy to replace this one.

    An implementation must be a **pure function of** ``(village, hazard,
    resident_id, dispatch_time_min, horizon_min)``.  It must not read the
    laboratory's ``truth/`` directory, and it must not see the information time
    -- the caller decides which hazard field is legitimate.
    """

    adapter_id: str

    def plan_and_evaluate(
        self,
        village: Village,
        hazard: ArrivalTimeHazard,
        resident_id: str,
        dispatch_time_min: float,
        horizon_min: float,
    ) -> MissionOutcome:
        """Find the earliest-completing feasible mission, or report why not."""
        ...

    def evaluate_plan(
        self, village: Village, hazard: ArrivalTimeHazard, plan: MissionPlan
    ) -> MissionOutcome:
        """Re-evaluate an existing plan against a (possibly different) field."""
        ...


def _edge_passable(
    hazard: ArrivalTimeHazard,
    edge: RoadEdge,
    t_enter_min: float,
    t_exit_min: float,
    semantics: str,
) -> bool:
    """Whether ``edge`` can be traversed over ``[t_enter, t_exit]``."""
    arrivals = hazard.arrival_at(np.asarray(edge.sample_xy_m))
    if semantics == "FULL_INTERVAL":
        return bool(np.min(arrivals) > t_exit_min)
    # POINT_IN_TIME: the vehicle only has to beat the fire to each point.
    n = len(arrivals)
    frac = np.linspace(0.0, 1.0, n)
    at_point = t_enter_min + frac * (t_exit_min - t_enter_min)
    return bool(np.all(arrivals > at_point))


def _exposure_min(
    hazard: ArrivalTimeHazard, edge: RoadEdge, t_enter_min: float, t_exit_min: float
) -> float:
    """Minutes of traversal spent on a corridor that has already burned.

    A *modelled* exposure proxy, not a dose model: the fraction of corridor
    sample points whose arrival time precedes the entry time, times the
    traversal duration.
    """
    arrivals = hazard.arrival_at(np.asarray(edge.sample_xy_m))
    frac_burned = float(np.mean(arrivals <= t_enter_min))
    return frac_burned * (t_exit_min - t_enter_min)


def _earliest_arrival_paths(
    village: Village,
    hazard: ArrivalTimeHazard,
    origin: str,
    t_start_min: float,
    semantics: str,
    speed_override_m_per_min: float | None = None,
) -> tuple[dict[str, float], dict[str, tuple[str, RoadEdge] | None]]:
    """Time-dependent Dijkstra from ``origin`` leaving at ``t_start_min``.

    Edge travel times are constant, so the network is FIFO and plain Dijkstra
    on arrival time is exact.  An edge is relaxed only if it is passable over
    the interval the vehicle would occupy it, which is what makes the result a
    *feasible* earliest-arrival tree rather than merely a shortest one.

    Returns:
        ``(arrival_time_by_node, predecessor_by_node)``.
    """
    adj = village.adjacency()
    best: dict[str, float] = {origin: float(t_start_min)}
    prev: dict[str, tuple[str, RoadEdge] | None] = {origin: None}
    queue: list[tuple[float, str]] = [(float(t_start_min), origin)]
    while queue:
        t_now, node = heapq.heappop(queue)
        if t_now > best.get(node, math.inf) + 1e-9:
            continue
        for edge in adj[node]:
            other = edge.v if edge.u == node else edge.u
            if speed_override_m_per_min is None:
                dt = edge.travel_time_min
            else:
                dt = edge.length_m / speed_override_m_per_min
            t_exit = t_now + dt
            if not _edge_passable(hazard, edge, t_now, t_exit, semantics):
                continue
            if t_exit < best.get(other, math.inf) - 1e-9:
                best[other] = t_exit
                prev[other] = (node, edge)
                heapq.heappush(queue, (t_exit, other))
    return best, prev


def _reconstruct(
    prev: dict[str, tuple[str, RoadEdge] | None],
    arrival: dict[str, float],
    origin: str,
    target: str,
) -> tuple[Leg, ...]:
    legs: list[Leg] = []
    node = target
    while node != origin:
        step = prev.get(node)
        if step is None:
            raise KeyError(f"no path from {origin} to {target}")
        parent, edge = step
        legs.append(
            Leg(
                edge_id=edge.edge_id,
                t_enter_min=float(arrival[parent]),
                t_exit_min=float(arrival[node]),
            )
        )
        node = parent
    return tuple(reversed(legs))


@dataclass(frozen=True)
class PlaceholderDispatchAdapter:
    """Minimal internal implementation of :class:`MissionFeasibilityAdapter`.

    Temporary.  Replaced wholesale when ``wildfireguardian-assisted-dispatch``
    becomes importable; the experiment depends on the protocol above, not on
    this class (``docs/DISPATCH_ADAPTER.md``).
    """

    adapter_id: str = "INTERNAL_PLACEHOLDER_V1"
    semantics: str = "FULL_INTERVAL"

    def __post_init__(self) -> None:
        if self.semantics not in TRAVERSAL_SEMANTICS:
            raise ValueError(
                f"unknown traversal semantics {self.semantics!r}; "
                f"expected one of {TRAVERSAL_SEMANTICS}"
            )

    def plan_and_evaluate(
        self,
        village: Village,
        hazard: ArrivalTimeHazard,
        resident_id: str,
        dispatch_time_min: float,
        horizon_min: float,
    ) -> MissionOutcome:
        residents = {r.resident_id: r for r in village.residents}
        resident = residents[resident_id]

        # Check the resident before the roads.  When the house is already
        # burning, "no route to the resident" is true but useless: the reason
        # the mission cannot happen is the fire at the house, and the failure
        # taxonomy in FAILURE_ANALYSIS.md depends on saying so.
        house_arrival = float(
            hazard.arrival_at(np.array([[resident.x_m, resident.y_m]]))[0]
        )
        if house_arrival <= dispatch_time_min + resident.pickup_duration_min:
            return MissionOutcome(
                feasible=False,
                reason="FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE",
                adapter_id=self.adapter_id,
            )

        out_arr, out_prev = _earliest_arrival_paths(
            village, hazard, village.base_node, dispatch_time_min, self.semantics
        )
        t_reach = out_arr.get(resident.node_id)
        if t_reach is None:
            return MissionOutcome(
                feasible=False,
                reason="NO_ROUTE_TO_RESIDENT",
                adapter_id=self.adapter_id,
            )
        # The resident must still be reachable before the fire arrives at the
        # house, and must remain so for the whole pickup.
        pickup_end = t_reach + resident.pickup_duration_min
        if house_arrival <= pickup_end:
            return MissionOutcome(
                feasible=False,
                reason="FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE",
                adapter_id=self.adapter_id,
            )

        in_arr, in_prev = _earliest_arrival_paths(
            village, hazard, resident.node_id, pickup_end, self.semantics
        )
        reachable = [
            (in_arr[d], d) for d in village.destination_nodes if d in in_arr
        ]
        if not reachable:
            return MissionOutcome(
                feasible=False,
                reason="NO_ROUTE_TO_DESTINATION",
                adapter_id=self.adapter_id,
            )
        t_done, dest = min(reachable)
        if t_done > horizon_min:
            return MissionOutcome(
                feasible=False,
                reason="MISSION_EXCEEDS_HORIZON",
                adapter_id=self.adapter_id,
            )

        outbound = _reconstruct(out_prev, out_arr, village.base_node, resident.node_id)
        inbound = _reconstruct(in_prev, in_arr, resident.node_id, dest)
        plan = MissionPlan(
            resident_id=resident_id,
            dispatch_time_min=float(dispatch_time_min),
            outbound=outbound,
            inbound=inbound,
            destination_node=dest,
            pickup_start_min=float(t_reach),
            pickup_end_min=float(pickup_end),
            completion_time_min=float(t_done),
        )
        return self.evaluate_plan(village, hazard, plan)

    def evaluate_plan(
        self, village: Village, hazard: ArrivalTimeHazard, plan: MissionPlan
    ) -> MissionOutcome:
        """Re-evaluate a plan against a field -- the paired-world workhorse.

        A plan formed under a forecast is replayed here against hidden truth.
        Nothing about the plan changes; only the field answering the hazard
        question does.
        """
        residents = {r.resident_id: r for r in village.residents}
        resident = residents[plan.resident_id]
        house_arrival = float(
            hazard.arrival_at(np.array([[resident.x_m, resident.y_m]]))[0]
        )
        if house_arrival <= plan.pickup_end_min:
            return MissionOutcome(
                feasible=False,
                reason="FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE",
                plan=plan,
                adapter_id=self.adapter_id,
            )

        edges = village.edge_by_id()
        exposure = 0.0
        for leg in plan.all_legs():
            edge = edges[leg.edge_id]
            if not _edge_passable(
                hazard, edge, leg.t_enter_min, leg.t_exit_min, self.semantics
            ):
                return MissionOutcome(
                    feasible=False,
                    reason="ROUTE_BLOCKED_BY_FIRE",
                    plan=plan,
                    blocked_edge_id=leg.edge_id,
                    adapter_id=self.adapter_id,
                )
            exposure += _exposure_min(hazard, edge, leg.t_enter_min, leg.t_exit_min)

        return MissionOutcome(
            feasible=True,
            reason="COMPLETED",
            plan=plan,
            responder_exposure_min=float(exposure),
            adapter_id=self.adapter_id,
        )

    def self_evacuation_feasible(
        self,
        village: Village,
        hazard: ArrivalTimeHazard,
        resident_id: str,
        start_time_min: float,
        horizon_min: float,
    ) -> MissionOutcome:
        """Whether the resident could reach a destination unaided.

        Evaluated separately and never inferred from the assisted result: a
        resident with no self-evacuation route is not thereby a rescue case,
        and a feasible self-evacuation does not make assistance unnecessary
        (PROTOCOL.md section 6).
        """
        residents = {r.resident_id: r for r in village.residents}
        resident = residents[resident_id]
        if not resident.self_evacuation_capable:
            return MissionOutcome(
                feasible=False,
                reason="RESIDENT_NOT_SELF_EVACUATION_CAPABLE",
                adapter_id=self.adapter_id,
            )
        arr, _ = _earliest_arrival_paths(
            village,
            hazard,
            resident.node_id,
            start_time_min,
            self.semantics,
            speed_override_m_per_min=SELF_EVAC_SPEED_M_PER_MIN,
        )
        reachable = [arr[d] for d in village.destination_nodes if d in arr]
        if not reachable or min(reachable) > horizon_min:
            return MissionOutcome(
                feasible=False,
                reason="NO_SELF_EVACUATION_ROUTE",
                adapter_id=self.adapter_id,
            )
        return MissionOutcome(
            feasible=True,
            reason="SELF_EVACUATION_COMPLETED",
            adapter_id=self.adapter_id,
            extras={"completion_time_min": float(min(reachable))},
        )


def classify_outcome(assisted: MissionOutcome, self_evac: MissionOutcome) -> str:
    """Combine the two independently-evaluated modes into an outcome state."""
    if assisted.feasible and self_evac.feasible:
        return "BOTH_FEASIBLE"
    if assisted.feasible:
        return "ASSISTANCE_FEASIBLE"
    if self_evac.feasible:
        return "SELF_EVACUATION_FEASIBLE"
    return "NO_FEASIBLE_MISSION_FOUND"
