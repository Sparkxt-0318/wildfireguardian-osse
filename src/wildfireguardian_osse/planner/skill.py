"""Forecast skill, measured separately from decision value.

The experiment asks explicitly whether conventional skill is *sufficient* to
predict decision value.  That question only has meaning if the two are computed
independently, so nothing here looks at a policy, an action or a loss.

All metrics compare a forecast against hidden truth and are therefore
evaluator-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ..landscape.grid import Grid
from .forecast import Forecast
from .sandbox import assert_evaluator_context


@dataclass(frozen=True)
class ForecastSkill:
    """Conventional skill scores over a forecast's valid window."""

    csi: float                      # critical success index of burned-by-valid_to
    iou: float                      # same thing, reported under its other name
    front_displacement_m: float     # centroid gap of newly burned area
    arrival_mae_min: float          # over cells both predict and truth burn
    missed_event_rate: float        # truth-burned cells not predicted
    false_alarm_rate: float         # predicted-burned cells that do not burn
    n_truth_cells: int
    n_forecast_cells: int

    def as_dict(self) -> dict:
        return {f"skill_{k}": v for k, v in asdict(self).items()}


def score_forecast(
    forecast: Forecast, truth_arrival_min: np.ndarray, grid: Grid
) -> ForecastSkill:
    """Score a forecast against hidden truth over ``[valid_from, valid_to]``.

    Cells already burned at ``valid_from`` are excluded from every metric: a
    forecast gets no credit for the fire that had already happened when it was
    issued, which is what separates a forecast from a current-state estimate.
    """
    assert_evaluator_context("forecast skill scoring (reads hidden truth)")

    truth = np.asarray(truth_arrival_min, dtype=float)
    pred = np.asarray(forecast.arrival_time_min, dtype=float)
    t0, t1 = forecast.valid_from_min, forecast.valid_to_min

    already = truth <= t0
    truth_new = np.isfinite(truth) & (truth > t0) & (truth <= t1) & ~already
    pred_new = np.isfinite(pred) & (pred > t0) & (pred <= t1) & ~already

    hits = int(np.count_nonzero(truth_new & pred_new))
    misses = int(np.count_nonzero(truth_new & ~pred_new))
    false_alarms = int(np.count_nonzero(pred_new & ~truth_new))
    denominator = hits + misses + false_alarms
    csi = float(hits / denominator) if denominator else float("nan")

    X, Y = grid.cell_centres()
    if np.any(truth_new) and np.any(pred_new):
        displacement = float(
            np.hypot(
                X[pred_new].mean() - X[truth_new].mean(),
                Y[pred_new].mean() - Y[truth_new].mean(),
            )
        )
    else:
        displacement = float("nan")

    both = truth_new & pred_new
    mae = float(np.abs(truth[both] - pred[both]).mean()) if np.any(both) else float("nan")

    n_truth = int(np.count_nonzero(truth_new))
    n_pred = int(np.count_nonzero(pred_new))
    return ForecastSkill(
        csi=csi,
        iou=csi,
        front_displacement_m=displacement,
        arrival_mae_min=mae,
        missed_event_rate=float(misses / n_truth) if n_truth else float("nan"),
        false_alarm_rate=float(false_alarms / n_pred) if n_pred else float("nan"),
        n_truth_cells=n_truth,
        n_forecast_cells=n_pred,
    )
