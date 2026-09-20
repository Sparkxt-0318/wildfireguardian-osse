"""``D_s``: exactly the data a planner may use at information time ``s``.

The rule (``docs/TIME_SEMANTICS.md#2``): an observation may be used only at or
after its ``availability_time_min``.  A record acquired early but processed
late is unavailable until it is delivered.  :meth:`PlannerView.at` is the only
route to observations, and it asserts the filter it just applied rather than
trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from ..landscape.grid import Grid
from ..missions.village import WorldGeometry
from ..storage.reader import available_at

#: Tables the planner may see.  Anything not listed is not reachable.
PLANNER_TABLES: tuple[str, ...] = (
    "fire_detections",
    "fire_scan_log",
    "weather_observations",
)


@dataclass(frozen=True)
class AvailableData:
    """``D_s`` -- the observations usable at information time ``s``."""

    as_of_min: float
    fire_detections: dict[str, np.ndarray]
    fire_scan_log: dict[str, np.ndarray]
    weather_observations: dict[str, np.ndarray]

    def n_detections(self) -> int:
        return len(self.fire_detections.get("obs_id", []))

    def n_weather(self) -> int:
        return len(self.weather_observations.get("obs_id", []))


@dataclass(frozen=True)
class PlannerView:
    """Everything a planner is allowed to know about a world.

    Holds **no** reference to :class:`~wildfireguardian_osse.nature.world.NatureTruth`.
    Static context (terrain, coarse fuel class, the road network) is included
    because it is known before an incident and carries no temporal information
    (``docs/DECISIONS.md#d-006``).
    """

    grid: Grid
    geometry: WorldGeometry
    horizon_min: float
    elevation_m: np.ndarray
    fuel_class: np.ndarray
    published_specs: Mapping[str, Any]
    _tables: Mapping[str, dict[str, np.ndarray]] = field(repr=False)

    def at(self, s_min: float) -> AvailableData:
        """Return ``D_s``.

        Raises:
            AssertionError: if any returned record would be usable before its
                availability time.  The filter is asserted, not assumed.
        """
        out: dict[str, dict[str, np.ndarray]] = {}
        for name in PLANNER_TABLES:
            table = self._tables.get(name, {})
            subset = available_at(table, s_min) if table else {}
            column = subset.get("availability_time_min")
            if column is not None and len(column):
                worst = float(np.max(np.asarray(column, dtype=float)))
                if worst > float(s_min) + 1e-9:
                    raise AssertionError(
                        f"D_s leak: {name} returned a record available at "
                        f"{worst} for information time {s_min} "
                        "(docs/TIME_SEMANTICS.md#2)"
                    )
            out[name] = subset
        return AvailableData(
            as_of_min=float(s_min),
            fire_detections=out["fire_detections"],
            fire_scan_log=out["fire_scan_log"],
            weather_observations=out["weather_observations"],
        )


def build_planner_view(
    *,
    grid: Grid,
    geometry: WorldGeometry,
    horizon_min: float,
    elevation_m: np.ndarray,
    fuel_class: np.ndarray,
    observations,
) -> PlannerView:
    """Build a planner view from an observation bundle.

    Only the planner-visible tables are copied across.  The bundle's hidden
    by-products -- the detection ledger, the true sensor state, the generative
    parameters -- are **not** carried over, so they cannot be reached even by
    accident.
    """
    tables = {
        "fire_detections": dict(observations.fire_detections.columns),
        "fire_scan_log": dict(observations.fire_scan_log.columns),
        "weather_observations": dict(observations.weather_observations.columns),
    }
    for name, table in tables.items():
        forbidden = [c for c in table if "true_" in c or "kind" == c]
        if forbidden:
            raise AssertionError(f"{name} carries hidden column(s) {forbidden}")
    return PlannerView(
        grid=grid,
        geometry=geometry,
        horizon_min=float(horizon_min),
        elevation_m=np.asarray(elevation_m),
        fuel_class=np.asarray(fuel_class),
        published_specs=dict(observations.published_specs),
        _tables=tables,
    )
