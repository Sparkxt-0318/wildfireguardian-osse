"""Forecast skill, measured **separately** from decision value.

The experiment's second question is whether conventional skill is sufficient to
predict decision value.  That question only has content if skill is scored on
its own terms, with no reference to any policy, and then correlated with value
afterwards.  Nothing in this module knows a policy exists.

All metrics compare a forecast's predicted arrival-time field to the hidden
arrival-time field, coarsened to the forecast's own grid by block minimum.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .forecast import Forecast
from .world import ExperimentWorld


def _coarsen_min(field: np.ndarray, factor: int) -> np.ndarray:
    ny, nx = field.shape
    py, px = (-ny) % factor, (-nx) % factor
    if py or px:
        field = np.pad(field, ((0, py), (0, px)), constant_values=np.inf)
    ny, nx = field.shape
    return field.reshape(ny // factor, factor, nx // factor, factor).min(axis=(1, 3))


@dataclass(frozen=True)
class SkillScores:
    """Conventional forecast-skill metrics for one forecast.

    Attributes:
        csi: critical success index over the valid window
            ``hits / (hits + misses + false alarms)``.
        iou: identical to ``csi`` for a binary field; reported under both names
            because the two literatures use different words for it.
        pod: probability of detection ``hits / (hits + misses)``.
        far: false alarm ratio ``false alarms / (hits + false alarms)``.
        missed_event_rate: fraction of truly-burned cells the forecast did not
            predict to burn -- ``1 - pod``, reported separately because it is
            the quantity a protective action is most exposed to.
        front_displacement_m: distance between the centroid of the predicted
            burned set and that of the true burned set.
        arrival_mae_min: mean absolute arrival-time error over the hits.
        arrival_bias_min: signed mean error; positive means the forecast is
            late (predicted arrival after the true arrival).
        n_truth_cells / n_pred_cells: set sizes, so a degenerate score can be
            recognised rather than averaged into a table.
    """

    csi: float
    iou: float
    pod: float
    far: float
    missed_event_rate: float
    front_displacement_m: float
    arrival_mae_min: float
    arrival_bias_min: float
    n_truth_cells: int
    n_pred_cells: int

    def as_record(self) -> dict:
        return {
            "forecast_csi": self.csi,
            "forecast_iou": self.iou,
            "forecast_pod": self.pod,
            "forecast_far": self.far,
            "forecast_missed_event_rate": self.missed_event_rate,
            "forecast_front_displacement_m": self.front_displacement_m,
            "forecast_arrival_mae_min": self.arrival_mae_min,
            "forecast_arrival_bias_min": self.arrival_bias_min,
            "forecast_n_truth_cells": self.n_truth_cells,
            "forecast_n_pred_cells": self.n_pred_cells,
        }


def _nan() -> float:
    return float("nan")


def score_forecast(world: ExperimentWorld, forecast: Forecast) -> SkillScores:
    """Score one forecast against hidden truth over its own valid window.

    The comparison set is the cells that truly burn in ``[valid_from,
    valid_to]``.  Cells that had already burned before the forecast was issued
    are excluded from both sides: predicting the past is not skill.
    """
    factor = max(1, int(round(forecast.cell_size_m / world.truth.grid.cell_size_m)))
    truth = _coarsen_min(world.truth.arrival_time_min, factor)
    pred = forecast.predicted_arrival_time_min
    if truth.shape != pred.shape:
        ny = min(truth.shape[0], pred.shape[0])
        nx = min(truth.shape[1], pred.shape[1])
        truth, pred = truth[:ny, :nx], pred[:ny, :nx]

    lo, hi = forecast.valid_from_min, forecast.valid_to_min
    truth_set = (truth > lo) & (truth <= hi)
    pred_set = (pred > lo) & (pred <= hi)
    already = truth <= lo
    truth_set &= ~already
    pred_set &= ~already

    hits = int(np.count_nonzero(truth_set & pred_set))
    misses = int(np.count_nonzero(truth_set & ~pred_set))
    false_alarms = int(np.count_nonzero(~truth_set & pred_set))
    denom = hits + misses + false_alarms
    csi = hits / denom if denom else _nan()
    pod = hits / (hits + misses) if (hits + misses) else _nan()
    far = false_alarms / (hits + false_alarms) if (hits + false_alarms) else _nan()
    missed = 1.0 - pod if not np.isnan(pod) else _nan()

    if hits:
        err = pred[truth_set & pred_set] - truth[truth_set & pred_set]
        mae = float(np.mean(np.abs(err)))
        bias = float(np.mean(err))
    else:
        mae = bias = _nan()

    if truth_set.any() and pred_set.any():
        cs = forecast.cell_size_m
        ti, tj = np.nonzero(truth_set)
        pi, pj = np.nonzero(pred_set)
        disp = float(
            np.hypot(
                (pj.mean() - tj.mean()) * cs, (pi.mean() - ti.mean()) * cs
            )
        )
    else:
        disp = _nan()

    return SkillScores(
        csi=csi,
        iou=csi,
        pod=pod,
        far=far,
        missed_event_rate=missed,
        front_displacement_m=disp,
        arrival_mae_min=mae,
        arrival_bias_min=bias,
        n_truth_cells=int(np.count_nonzero(truth_set)),
        n_pred_cells=int(np.count_nonzero(pred_set)),
    )


def aggregate_skill(scores: list[SkillScores]) -> dict:
    """Mean of each metric over a list of forecasts, ignoring undefined ones."""
    if not scores:
        return {}
    out: dict[str, float] = {}
    for key in (
        "csi", "pod", "far", "missed_event_rate", "front_displacement_m",
        "arrival_mae_min", "arrival_bias_min",
    ):
        vals = [getattr(s, key) for s in scores]
        vals = [v for v in vals if v == v]  # drop NaN
        out[f"forecast_{key}"] = float(np.mean(vals)) if vals else _nan()
    out["forecast_n_scored"] = float(len(scores))
    return out
