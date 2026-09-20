"""Per-world geometry: village, responder base, destination and road network.

Generation rules are declared, not tuned to produce a desired answer
(``experiments/forecast_value_mve/PROTOCOL.md`` section 14, and the
world-generation audit in ``reports/MVE_METHOD.md``).

The one rule worth stating plainly: **the ignition is placed upwind of the
village**, at a declared distance with a declared bearing jitter.  Without it
most worlds would have no fire anywhere near the village and the experiment
would measure nothing.  It is a STRESS-TEST choice, not a claim about where
Korean fires start, and it biases the sample toward threatened villages by
construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..landscape.grid import Grid
from .network import RoadNetwork, build_road_network


@dataclass(frozen=True)
class WorldGeometry:
    """Static, planner-visible geometry of one world."""

    grid: Grid
    network: RoadNetwork
    ignition_xy_m: tuple[float, float]
    village_xy_m: tuple[float, float]
    n_residents: int

    def as_dict(self) -> dict:
        return {
            "nodes": {k: [float(v[0]), float(v[1])] for k, v in self.network.nodes.items()},
            "ignition_xy_m": [float(self.ignition_xy_m[0]), float(self.ignition_xy_m[1])],
            "n_residents": int(self.n_residents),
            "route_ids": list(self.network.route_ids),
        }


#: Declared geometry rules, in fractions of the domain.  ASSUMED throughout.
VILLAGE_FRAC = (0.52, 0.50)
DESTINATION_FRAC = (0.90, 0.72)
JUNCTION_DIRECT_FRAC = (0.72, 0.52)
JUNCTION_DETOUR_FRAC = (0.66, 0.84)
BASE_FRAC = (0.86, 0.18)

#: Ignition placement relative to the village.
IGNITION_UPWIND_DISTANCE_M = 1100.0
IGNITION_BEARING_JITTER_DEG = 30.0
IGNITION_DISTANCE_JITTER_M = 200.0


def build_geometry(
    grid: Grid,
    wind_dir_deg: float,
    rng: np.random.Generator,
    n_residents: int = 12,
) -> WorldGeometry:
    """Place the village, network and ignition for one world.

    Args:
        grid: raster geometry.
        wind_dir_deg: the direction the wind blows **toward**, CCW from east.
        rng: generator from the ``nature_seed`` sub-stream ``geometry``.  The
            geometry is part of the world, so it must not move when the
            observation configuration changes.
        n_residents: nested inside the world; not an independent unit.

    Returns:
        A :class:`WorldGeometry`.
    """
    w, h = grid.width_m, grid.height_m

    def place(frac: tuple[float, float]) -> tuple[float, float]:
        return (frac[0] * w, frac[1] * h)

    village = place(VILLAGE_FRAC)
    nodes = {
        "village": village,
        "destination": place(DESTINATION_FRAC),
        "junction_a": place(JUNCTION_DIRECT_FRAC),
        "junction_b": place(JUNCTION_DETOUR_FRAC),
        "base": place(BASE_FRAC),
    }

    # Upwind of the village: the wind blows toward wind_dir_deg, so the fire
    # must start on the opposite side to run at the village.
    bearing = np.deg2rad(wind_dir_deg + 180.0) + np.deg2rad(
        IGNITION_BEARING_JITTER_DEG
    ) * rng.standard_normal()
    distance = IGNITION_UPWIND_DISTANCE_M + IGNITION_DISTANCE_JITTER_M * rng.standard_normal()
    distance = float(np.clip(distance, 400.0, 0.45 * min(w, h)))
    ignition = (
        float(np.clip(village[0] + distance * np.cos(bearing), 0.04 * w, 0.96 * w)),
        float(np.clip(village[1] + distance * np.sin(bearing), 0.04 * h, 0.96 * h)),
    )

    return WorldGeometry(
        grid=grid,
        network=build_road_network(nodes),
        ignition_xy_m=ignition,
        village_xy_m=village,
        n_residents=int(n_residents),
    )
