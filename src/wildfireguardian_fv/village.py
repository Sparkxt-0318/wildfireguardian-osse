"""Village geometry: residents, a road graph, a responder base, safe destinations.

This is **planner-visible static context**: a dispatcher knows where the roads
and the houses are before the incident starts.  It is generated from the
experiment-side ``world_layout_seed`` stream, which is namespace-disjoint from
every laboratory stream, so the village provably cannot move the fire and the
fire provably cannot move the village (``rng.py``).

Geometry is deliberately terrain-independent (a perturbed lattice, not a valley
network).  That is an unrealism, recorded as ``ASSUMED`` in
``experiments/forecast_value_mve/reports/LIMITATIONS.md`` and in the
world-generation audit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

#: Road classes and their free travel speed in metres per minute.
#: ``ASSUMED`` -- no Korean road-speed source is used here
#: (``docs/ASSUMPTIONS.md`` conventions; see PROTOCOL.md section 10).
ROAD_SPEED_M_PER_MIN: dict[str, float] = {
    "spine": 700.0,     # ~42 km/h
    "minor": 400.0,     # ~24 km/h
    "driveway": 200.0,  # ~12 km/h
}


@dataclass(frozen=True)
class RoadEdge:
    """One traversable road segment between two node ids."""

    edge_id: str
    u: str
    v: str
    road_class: str
    length_m: float
    #: Sample points along the corridor, used to ask the hazard oracle whether
    #: the edge is burning.  Stored so hazard evaluation is identical whether
    #: the oracle wraps hidden truth or a forecast.
    sample_xy_m: tuple[tuple[float, float], ...]

    @property
    def travel_time_min(self) -> float:
        return self.length_m / ROAD_SPEED_M_PER_MIN[self.road_class]


@dataclass(frozen=True)
class Resident:
    """One protected site (a household).

    ``self_evacuation_capable`` is a *capability assumption*, not an inference
    from route existence.  The absence of a self-evacuation route never implies
    that rescue is required and vice versa (PROTOCOL.md section 6).
    """

    resident_id: str
    x_m: float
    y_m: float
    node_id: str
    self_evacuation_capable: bool
    pickup_duration_min: float


@dataclass(frozen=True)
class Village:
    """The full planner-visible static layout of one world."""

    village_id: str
    nodes: dict[str, tuple[float, float]]
    edges: tuple[RoadEdge, ...]
    residents: tuple[Resident, ...]
    base_node: str
    destination_nodes: tuple[str, ...]
    centre_xy_m: tuple[float, float]

    def adjacency(self) -> dict[str, list[RoadEdge]]:
        adj: dict[str, list[RoadEdge]] = {n: [] for n in self.nodes}
        for e in self.edges:
            adj[e.u].append(e)
            adj[e.v].append(e)
        return adj

    def edge_by_id(self) -> dict[str, RoadEdge]:
        return {e.edge_id: e for e in self.edges}

    def as_planner_dict(self) -> dict:
        """Serialisable form handed to the planner.

        Contains geometry only: no seed, no fire quantity, no future.
        """
        return {
            "village_id": self.village_id,
            "centre_xy_m": list(self.centre_xy_m),
            "base_node": self.base_node,
            "destination_nodes": list(self.destination_nodes),
            "nodes": {k: [float(v[0]), float(v[1])] for k, v in self.nodes.items()},
            "edges": [
                {
                    "edge_id": e.edge_id,
                    "u": e.u,
                    "v": e.v,
                    "road_class": e.road_class,
                    "length_m": round(e.length_m, 3),
                }
                for e in self.edges
            ],
            "residents": [
                {
                    "resident_id": r.resident_id,
                    "x_m": round(r.x_m, 3),
                    "y_m": round(r.y_m, 3),
                    "node_id": r.node_id,
                    "self_evacuation_capable": bool(r.self_evacuation_capable),
                    "pickup_duration_min": r.pickup_duration_min,
                }
                for r in self.residents
            ],
        }


@dataclass(frozen=True)
class VillageConfig:
    """Generation parameters for one village.  Every field is swept-able."""

    lattice_n: int = 6
    jitter_frac: float = 0.28
    p_edge_keep: float = 0.72
    n_residents: int = 6
    resident_radius_m: float = 900.0
    pickup_duration_min: float = 6.0
    p_self_evacuation_capable: float = 0.45
    #: Fraction of the domain half-width kept clear of the boundary.
    margin_frac: float = 0.08
    corridor_sample_m: float = 60.0


def _sample_points(a: tuple[float, float], b: tuple[float, float], step_m: float):
    """Sample points along a segment, endpoints included."""
    length = math.dist(a, b)
    n = max(2, int(math.ceil(length / step_m)) + 1)
    ts = np.linspace(0.0, 1.0, n)
    return tuple(
        (float(a[0] + t * (b[0] - a[0])), float(a[1] + t * (b[1] - a[1]))) for t in ts
    )


def _connected(nodes: Iterable[str], edges: Iterable[RoadEdge]) -> bool:
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        adj[e.u].append(e.v)
        adj[e.v].append(e.u)
    start = next(iter(adj), None)
    if start is None:
        return True
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        for nxt in adj[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return len(seen) == len(adj)


def build_village(
    cfg: VillageConfig,
    width_m: float,
    height_m: float,
    rng: np.random.Generator,
    village_id: str = "village",
) -> Village:
    """Build a perturbed-lattice road network with houses, a base and exits.

    Args:
        cfg: generation parameters.
        width_m, height_m: domain extent.
        rng: a generator from the ``world_layout_seed`` stream.
        village_id: identifier written into records.

    Returns:
        A :class:`Village`.  Guaranteed connected: edges are thinned at random
        but any thinning that disconnects the graph is rejected, so every world
        has at least one base-to-destination path in the absence of fire.

    Note:
        Sub-stream discipline: the number of draws here depends on ``cfg``
        only, never on the fire, because this function never sees the fire.
    """
    n = int(cfg.lattice_n)
    mx, my = cfg.margin_frac * width_m, cfg.margin_frac * height_m
    xs = np.linspace(mx, width_m - mx, n)
    ys = np.linspace(my, height_m - my, n)
    jitter_x = cfg.jitter_frac * (xs[1] - xs[0])
    jitter_y = cfg.jitter_frac * (ys[1] - ys[0])

    nodes: dict[str, tuple[float, float]] = {}
    for i in range(n):
        for j in range(n):
            interior = 0 < i < n - 1 and 0 < j < n - 1
            dx = float(rng.uniform(-jitter_x, jitter_x)) if interior else 0.0
            dy = float(rng.uniform(-jitter_y, jitter_y)) if interior else 0.0
            nodes[f"n{i}_{j}"] = (float(xs[j] + dx), float(ys[i] + dy))

    # Candidate lattice edges (4-neighbour).  The middle row and column are
    # "spine" roads; everything else is minor.
    mid = n // 2
    candidates: list[tuple[str, str, str]] = []
    for i in range(n):
        for j in range(n):
            here = f"n{i}_{j}"
            if j + 1 < n:
                cls = "spine" if i == mid else "minor"
                candidates.append((here, f"n{i}_{j+1}", cls))
            if i + 1 < n:
                cls = "spine" if j == mid else "minor"
                candidates.append((here, f"n{i+1}_{j}", cls))

    keep = [c for c in candidates if c[2] == "spine"]
    optional = [c for c in candidates if c[2] != "spine"]
    draws = rng.random(len(optional))
    keep += [c for c, d in zip(optional, draws) if d < cfg.p_edge_keep]
    # Restore connectivity deterministically by re-adding thinned edges in
    # their canonical order until the graph is connected again.
    dropped = [c for c, d in zip(optional, draws) if d >= cfg.p_edge_keep]

    def _mk(u: str, v: str, cls: str) -> RoadEdge:
        a, b = nodes[u], nodes[v]
        return RoadEdge(
            edge_id=f"{u}->{v}",
            u=u,
            v=v,
            road_class=cls,
            length_m=float(math.dist(a, b)),
            sample_xy_m=_sample_points(a, b, cfg.corridor_sample_m),
        )

    edges = [_mk(*c) for c in keep]
    for c in dropped:
        if _connected(nodes, edges):
            break
        edges.append(_mk(*c))

    # Base at a corner node; destinations at the two far lattice corners.
    base_node = "n0_0"
    destination_nodes = (f"n{n-1}_{n-1}", f"n0_{n-1}")

    centre = (float(np.mean(xs)), float(np.mean(ys)))
    residents: list[Resident] = []
    interior_nodes = [f"n{i}_{j}" for i in range(1, n - 1) for j in range(1, n - 1)]
    for k in range(int(cfg.n_residents)):
        angle = float(rng.uniform(0.0, 2.0 * math.pi))
        radius = float(cfg.resident_radius_m * math.sqrt(rng.random()))
        rx = float(np.clip(centre[0] + radius * math.cos(angle), mx, width_m - mx))
        ry = float(np.clip(centre[1] + radius * math.sin(angle), my, height_m - my))
        node = min(interior_nodes, key=lambda nid: math.dist(nodes[nid], (rx, ry)))
        capable = bool(rng.random() < cfg.p_self_evacuation_capable)
        residents.append(
            Resident(
                resident_id=f"r{k:02d}",
                x_m=rx,
                y_m=ry,
                node_id=node,
                self_evacuation_capable=capable,
                pickup_duration_min=float(cfg.pickup_duration_min),
            )
        )

    # Driveways: each resident gets its own access node so that a pickup is a
    # real detour rather than a free stop at a junction.
    for r in residents:
        nid = f"h_{r.resident_id}"
        nodes[nid] = (r.x_m, r.y_m)
        edges.append(_mk(r.node_id, nid, "driveway"))
    residents = [
        Resident(
            resident_id=r.resident_id,
            x_m=r.x_m,
            y_m=r.y_m,
            node_id=f"h_{r.resident_id}",
            self_evacuation_capable=r.self_evacuation_capable,
            pickup_duration_min=r.pickup_duration_min,
        )
        for r in residents
    ]

    return Village(
        village_id=village_id,
        nodes=nodes,
        edges=tuple(edges),
        residents=tuple(residents),
        base_node=base_node,
        destination_nodes=destination_nodes,
        centre_xy_m=centre,
    )
