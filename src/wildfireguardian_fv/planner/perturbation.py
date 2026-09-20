"""Mode A: controlled perturbation of hidden truth.

**This module reads hidden truth on purpose.**  It is evaluator-side
machinery for isolating the causal effect of one error family, not a planner.
Nothing here ever sees an :class:`~wildfireguardian_fv.info.InformationSet`,
and the runner never routes its output through the leakage guard as if it
were a planner product -- the records it produces are labelled
``CONTROLLED_PERTURBATION`` so that no downstream reader can mistake a Mode A
result for evidence about what a real planner could achieve
(LEAKAGE_AUDIT.md section 4).

What it gives, that Mode B cannot: an error of *exactly* the declared
magnitude and no other. That is what makes the response surface attributable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .. import DEGRADATION_MODEL_VERSION
from ..degradation import DegradationSpec
from ..forecast import Forecast
from ..world import ExperimentWorld

#: Same decision grid as Mode B, so the two modes are scored identically.
from .independent import DECISION_CELL_SIZE_M, DEFAULT_LEAD_MIN


def _coarsen_min(field: np.ndarray, factor: int) -> np.ndarray:
    """Block-minimum coarsening: the earliest arrival within each block.

    Minimum, not mean: a decision cell is threatened as soon as any part of it
    burns, and ``+inf`` cells must not drag a finite block to ``+inf``.
    """
    ny, nx = field.shape
    py = (-ny) % factor
    px = (-nx) % factor
    if py or px:
        field = np.pad(field, ((0, py), (0, px)), constant_values=np.inf)
    ny, nx = field.shape
    return field.reshape(ny // factor, factor, nx // factor, factor).min(axis=(1, 3))


@dataclass(frozen=True)
class ControlledPerturbationForecaster:
    """Builds a forecast by degrading the hidden arrival-time field."""

    cell_size_m: float = DECISION_CELL_SIZE_M
    lead_min: float = DEFAULT_LEAD_MIN
    model_version: str = DEGRADATION_MODEL_VERSION

    def forecast(
        self,
        world: ExperimentWorld,
        information_time_min: float,
        degradation: DegradationSpec,
    ) -> Forecast:
        """Issue a perturbed-truth forecast valid over ``[s, s + lead]``.

        The perturbations are applied about the true ignition point, so a
        directional error rotates the *pattern* coherently rather than
        scrambling it.

        Args:
            world: the hidden world (evaluator-side).
            information_time_min: ``s``.
            degradation: the declared error regime.

        Returns:
            A :class:`~wildfireguardian_fv.forecast.Forecast` in mode
            ``CONTROLLED_PERTURBATION``.
        """
        s = float(information_time_min)
        availability = s + float(degradation.latency_min)
        valid_to = min(s + self.lead_min, float(world.horizon_min))

        fine = world.truth.arrival_time_min
        factor = max(1, int(round(self.cell_size_m / world.truth.grid.cell_size_m)))
        truth_coarse = _coarsen_min(fine, factor)

        ign = world.config.nature.ignitions[0]
        x0, y0 = float(ign.x_m), float(ign.y_m)
        t0 = float(ign.time_min)

        ny, nx = truth_coarse.shape
        xs = (np.arange(nx) + 0.5) * self.cell_size_m
        ys = (np.arange(ny) + 0.5) * self.cell_size_m
        gx, gy = np.meshgrid(xs, ys)

        # Sample the truth field at back-rotated, back-translated coordinates:
        # the resulting field is the truth pattern rotated by +bias and
        # translated by +displacement.
        dx, dy = gx - x0, gy - y0
        theta = -math.radians(float(degradation.direction_bias_deg))
        rx = dx * math.cos(theta) - dy * math.sin(theta)
        ry = dx * math.sin(theta) + dy * math.cos(theta)
        bearing = math.radians(float(degradation.displacement_bearing_deg))
        rx -= float(degradation.displacement_m) * math.cos(bearing)
        ry -= float(degradation.displacement_m) * math.sin(bearing)

        j = np.clip(((rx + x0) / self.cell_size_m).astype(int), 0, nx - 1)
        i = np.clip(((ry + y0) / self.cell_size_m).astype(int), 0, ny - 1)
        inside = (
            (rx + x0 >= 0) & (rx + x0 < nx * self.cell_size_m)
            & (ry + y0 >= 0) & (ry + y0 < ny * self.cell_size_m)
        )
        predicted = np.where(inside, truth_coarse[i, j], np.inf)

        if degradation.missed_spotting:
            predicted = self._remove_spot_area(world, predicted, factor)

        finite = np.isfinite(predicted)
        predicted = np.where(
            finite, t0 + (predicted - t0) * float(degradation.rate_bias_factor), np.inf
        )
        predicted = np.where(predicted <= valid_to, predicted, np.inf)

        prov = ("CONTROLLED_PERTURBATION", f"degradation:{self.model_version}")
        prov += degradation.provenance()
        return Forecast(
            forecast_id=f"w{world.world_id}-s{s:g}-{degradation.label}-modeA",
            mode="CONTROLLED_PERTURBATION",
            status="ISSUED",
            issue_time_min=s,
            availability_time_min=availability,
            valid_from_min=s,
            valid_to_min=valid_to,
            cell_size_m=self.cell_size_m,
            predicted_arrival_time_min=predicted,
            provenance=prov,
            diagnostics={
                "reference_xy_m": [x0, y0],
                "n_spot_events_removed": (
                    sum(1 for e in world.truth.spot_events if e.ignited)
                    if degradation.missed_spotting
                    else 0
                ),
            },
        )

    @staticmethod
    def _remove_spot_area(
        world: ExperimentWorld, predicted: np.ndarray, factor: int
    ) -> np.ndarray:
        """Drop the area attributable to spot ignitions from the prediction.

        Attribution is deliberately crude and generous to the forecast: cells
        closer to a spot ignition than to the main ignition, which burned after
        that spot started, are removed.  A finer attribution would need the
        propagation history, which the nature model does not retain.
        """
        if not world.truth.spot_events:
            return predicted
        ny, nx = predicted.shape
        cs = world.truth.grid.cell_size_m * factor
        xs = (np.arange(nx) + 0.5) * cs
        ys = (np.arange(ny) + 0.5) * cs
        gx, gy = np.meshgrid(xs, ys)
        ign = world.config.nature.ignitions[0]
        d_main = np.hypot(gx - float(ign.x_m), gy - float(ign.y_m))
        out = predicted.copy()
        for spot in world.truth.spot_events:
            if not spot.ignited:
                continue
            sx, sy = float(spot.land_x_m), float(spot.land_y_m)
            st = float(spot.time_min)
            d_spot = np.hypot(gx - sx, gy - sy)
            mask = (d_spot < d_main) & (out >= st)
            out = np.where(mask, np.inf, out)
        return out
