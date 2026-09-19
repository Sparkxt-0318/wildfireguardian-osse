"""Stochastic downwind spot ignition.

Optional and disabled by default.  When disabled the ``spotting_seed`` stream
is not consumed at all, so ``enabled: false`` reproduces exactly a model
without spotting (validation world V6, ``tests/test_spotting.py``).

Spot ignitions are hidden truth.  A planner can learn about them only through
the ordinary detection process -- they are never written to a planner-facing
file (``docs/NATURE_MODEL.md#5``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ..config import SpottingConfig
from ..landscape.grid import Grid


@dataclass(frozen=True)
class SpotEvent:
    """One firebrand attempt, successful or not.  Hidden truth."""

    time_min: float
    origin_x_m: float
    origin_y_m: float
    land_x_m: float
    land_y_m: float
    distance_m: float
    bearing_deg: float
    ignited: bool
    reason: str  # "ignited" | "outside_domain" | "already_burned" | "nonburnable" | "no_ignition"

    def to_dict(self) -> dict:
        return asdict(self)


class SpottingProcess:
    """Generates spot ignitions at fixed intervals during propagation.

    The process is invoked from the propagation step hook.  It fires only at
    multiples of ``interval_min`` so that its random consumption is a function
    of simulated time and of the fire state at those instants -- both of which
    are identical between a short and a long run of the same world, which is
    what keeps prefix causality intact (``docs/TIME_SEMANTICS.md#6``).
    """

    def __init__(
        self,
        cfg: SpottingConfig,
        grid: Grid,
        burnable: np.ndarray,
        fuel_multiplier: np.ndarray,
        wind_dir_at,
        residence_time_min: float,
        rng: np.random.Generator,
    ) -> None:
        self.cfg = cfg
        self.grid = grid
        self.burnable = burnable
        self.fuel_multiplier = fuel_multiplier
        self.wind_dir_at = wind_dir_at
        self.residence_time_min = float(residence_time_min)
        self.rng = rng
        self.events: list[SpotEvent] = []
        self._next_event_min = float(cfg.interval_min)

    def step(self, t_min: float, arrival_time_min: np.ndarray) -> None:
        """Step hook: maybe launch firebrands at time ``t_min``."""
        if not self.cfg.enabled:
            return
        while t_min + 1e-9 >= self._next_event_min:
            self._launch(self._next_event_min, arrival_time_min)
            self._next_event_min += float(self.cfg.interval_min)

    # -- internals -------------------------------------------------------
    def _launch(self, t_min: float, arrival_time_min: np.ndarray) -> None:
        active = (arrival_time_min <= t_min) & (
            arrival_time_min > t_min - self.residence_time_min
        )
        n_active = int(np.count_nonzero(active))
        if n_active == 0:
            return

        area_ha = n_active * self.grid.cell_area_m2 / 10_000.0
        lam = float(self.cfg.rate_per_ha_per_min) * area_ha * float(self.cfg.interval_min)
        n_brands = int(min(self.rng.poisson(lam), self.cfg.max_spots_per_event))
        if n_brands <= 0:
            return

        idx = np.flatnonzero(active)
        chosen = self.rng.choice(idx, size=n_brands, replace=True)
        rows, cols = np.unravel_index(chosen, active.shape)
        ox, oy = self.grid.ij_to_xy(rows, cols)

        mu = float(np.log(self.cfg.median_distance_m))
        distances = self.rng.lognormal(mean=mu, sigma=float(self.cfg.sigma_log), size=n_brands)
        wind_dir = float(self.wind_dir_at(t_min))
        bearings = wind_dir + np.deg2rad(self.cfg.bearing_sigma_deg) * self.rng.standard_normal(
            n_brands
        )
        lx = ox + distances * np.cos(bearings)
        ly = oy + distances * np.sin(bearings)
        ignition_draw = self.rng.random(n_brands)

        for b in range(n_brands):
            event = self._resolve(
                t_min,
                float(ox[b]),
                float(oy[b]),
                float(lx[b]),
                float(ly[b]),
                float(distances[b]),
                float(bearings[b]),
                float(ignition_draw[b]),
                arrival_time_min,
            )
            self.events.append(event)

    def _resolve(
        self,
        t_min: float,
        ox: float,
        oy: float,
        lx: float,
        ly: float,
        distance: float,
        bearing: float,
        draw: float,
        arrival_time_min: np.ndarray,
    ) -> SpotEvent:
        def make(ignited: bool, reason: str) -> SpotEvent:
            return SpotEvent(
                time_min=float(t_min),
                origin_x_m=ox,
                origin_y_m=oy,
                land_x_m=lx,
                land_y_m=ly,
                distance_m=distance,
                bearing_deg=float(np.rad2deg(bearing) % 360.0),
                ignited=ignited,
                reason=reason,
            )

        if not bool(self.grid.contains(np.array(lx), np.array(ly))):
            return make(False, "outside_domain")
        i, j = self.grid.xy_to_ij(lx, ly)
        if np.isfinite(arrival_time_min[i, j]):
            return make(False, "already_burned")
        if not self.burnable[i, j]:
            return make(False, "nonburnable")
        p = float(self.cfg.p_ignite) * float(min(1.0, self.fuel_multiplier[i, j]))
        if draw >= p:
            return make(False, "no_ignition")
        arrival_time_min[i, j] = float(t_min)
        return make(True, "ignited")

    @property
    def n_ignited(self) -> int:
        return sum(1 for e in self.events if e.ignited)
