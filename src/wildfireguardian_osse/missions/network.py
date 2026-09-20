"""Road network over the raster.

Deliberately small: a handful of nodes and straight edges, enough to give every
world at least two routes from the village to the destination that differ in
their exposure to the fire.  That difference is what makes route choice, and
therefore forecast value, possible at all.

Edges are sampled into raster cells so that a mission can be replayed against
any arrival-time field -- hidden truth for the evaluator, a forecast for the
planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..landscape.grid import Grid


@dataclass(frozen=True)
class Edge:
    """A straight road segment between two points, in local metres."""

    edge_id: str
    x0_m: float
    y0_m: float
    x1_m: float
    y1_m: float

    @property
    def length_m(self) -> float:
        return float(np.hypot(self.x1_m - self.x0_m, self.y1_m - self.y0_m))

    def sample_cells(self, grid: Grid, step_m: float | None = None):
        """Cells the segment passes through, with their fractional positions.

        Returns:
            ``(rows, cols, fractions)`` where ``fractions[k]`` is how far along
            the edge cell ``k`` sits, in ``[0, 1]``.  Duplicate cells are kept
            only at their first (earliest) fraction, which is the moment a
            vehicle first occupies them.
        """
        step = float(step_m if step_m is not None else grid.cell_size_m * 0.5)
        n = max(2, int(np.ceil(self.length_m / step)) + 1)
        fractions = np.linspace(0.0, 1.0, n)
        xs = self.x0_m + (self.x1_m - self.x0_m) * fractions
        ys = self.y0_m + (self.y1_m - self.y0_m) * fractions
        cols = np.clip((xs / grid.cell_size_m).astype(int), 0, grid.nx - 1)
        rows = np.clip((ys / grid.cell_size_m).astype(int), 0, grid.ny - 1)

        seen: dict[tuple[int, int], float] = {}
        for r, c, f in zip(rows, cols, fractions):
            key = (int(r), int(c))
            if key not in seen:
                seen[key] = float(f)
        keys = list(seen)
        return (
            np.array([k[0] for k in keys], dtype=int),
            np.array([k[1] for k in keys], dtype=int),
            np.array([seen[k] for k in keys], dtype=float),
        )


@dataclass(frozen=True)
class Route:
    """An ordered sequence of edges from an origin to a destination."""

    route_id: str
    edges: tuple[Edge, ...]

    @property
    def length_m(self) -> float:
        return float(sum(e.length_m for e in self.edges))

    def travel_time_min(self, speed_m_per_min: float) -> float:
        return self.length_m / float(speed_m_per_min)


@dataclass(frozen=True)
class RoadNetwork:
    """Named points plus the routes between the ones the experiment uses."""

    nodes: dict[str, tuple[float, float]]
    evacuation_routes: tuple[Route, ...]
    approach_route: Route  # responder base -> village

    @property
    def route_ids(self) -> tuple[str, ...]:
        return tuple(r.route_id for r in self.evacuation_routes)

    def route(self, route_id: str) -> Route:
        for candidate in self.evacuation_routes:
            if candidate.route_id == route_id:
                return candidate
        raise KeyError(f"unknown route {route_id!r}; have {self.route_ids}")


def _edge(edge_id: str, a: tuple[float, float], b: tuple[float, float]) -> Edge:
    return Edge(edge_id=edge_id, x0_m=a[0], y0_m=a[1], x1_m=b[0], y1_m=b[1])


def build_road_network(nodes: dict[str, tuple[float, float]]) -> RoadNetwork:
    """Assemble the standard MVE network from named nodes.

    Required nodes: ``village``, ``destination``, ``base``, ``junction_a``
    (the direct route) and ``junction_b`` (the longer detour).

    The two evacuation routes are deliberately asymmetric: ``route_direct`` is
    shorter but runs closer to the fire axis, ``route_detour`` is longer but
    swings away from it.  A policy that can anticipate the fire can prefer the
    detour before the direct route closes; one that cannot, cannot.
    """
    missing = {"village", "destination", "base", "junction_a", "junction_b"} - set(nodes)
    if missing:
        raise ValueError(f"road network is missing node(s): {sorted(missing)}")

    village, dest = nodes["village"], nodes["destination"]
    ja, jb, base = nodes["junction_a"], nodes["junction_b"], nodes["base"]

    direct = Route(
        route_id="route_direct",
        edges=(_edge("direct_1", village, ja), _edge("direct_2", ja, dest)),
    )
    detour = Route(
        route_id="route_detour",
        edges=(_edge("detour_1", village, jb), _edge("detour_2", jb, dest)),
    )
    approach = Route(route_id="route_approach", edges=(_edge("approach_1", base, village),))
    return RoadNetwork(
        nodes=dict(nodes), evacuation_routes=(direct, detour), approach_route=approach
    )
