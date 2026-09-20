"""Belief fields: what a policy thinks the hazard is, built from ``D_s`` only.

Both policies express their belief as an
:class:`~wildfireguardian_fv.dispatch.ArrivalTimeHazard`, the same type the
evaluator wraps hidden truth in.  A mission is therefore planned and judged by
identical code; only the field differs.  That is what makes a scenario
*coherent* rather than two loosely-related calculations.
"""

from __future__ import annotations

import numpy as np

from ..dispatch import ArrivalTimeHazard
from ..forecast import Forecast
from ..info import InformationSet

#: Belief-grid cell size, metres.  Matches the forecast decision grid.
BELIEF_CELL_SIZE_M = 120.0


def _grid_shape(info: InformationSet, cell_size_m: float) -> tuple[int, int]:
    w = float(info.grid_meta["width_m"])
    h = float(info.grid_meta["height_m"])
    return (int(np.ceil(h / cell_size_m)), int(np.ceil(w / cell_size_m)))


def distance_to_detections_m(
    info: InformationSet, cell_size_m: float = BELIEF_CELL_SIZE_M
) -> np.ndarray:
    """Distance from each belief cell to the nearest available detection.

    ``+inf`` everywhere when nothing has been detected yet, which is the
    honest representation of "no fire evidence" -- not "no fire".
    """
    shape = _grid_shape(info, cell_size_m)
    det = info.fire_detections
    if det.get("x_m") is None or len(det["x_m"]) == 0:
        return np.full(shape, np.inf)
    xs = (np.arange(shape[1]) + 0.5) * cell_size_m
    ys = (np.arange(shape[0]) + 0.5) * cell_size_m
    gx, gy = np.meshgrid(xs, ys)
    dx = det["x_m"].astype(float)
    dy = det["y_m"].astype(float)
    best = np.full(shape, np.inf)
    for x, y in zip(dx, dy):
        np.minimum(best, np.hypot(gx - x, gy - y), out=best)
    return best


def observed_fire_hazard(
    info: InformationSet,
    buffer_m: float,
    cell_size_m: float = BELIEF_CELL_SIZE_M,
) -> ArrivalTimeHazard:
    """"Everything within ``buffer_m`` of an observed detection is impassable."

    The buffer stands in for everything the policy does not know: where the
    fire has spread since the last scan, where the detection actually was, and
    where it is going.  It is a *static* belief -- arrival time ``0`` inside,
    ``+inf`` outside -- because a trigger/buffer policy makes no claim about
    the future.
    """
    dist = distance_to_detections_m(info, cell_size_m)
    field = np.where(dist <= buffer_m, 0.0, np.inf)
    return ArrivalTimeHazard(
        arrival_time_min=field,
        cell_size_m=cell_size_m,
        source=f"OBSERVED_FIRE_BUFFER_{buffer_m:g}m",
    )


def observed_arrival_estimate(
    info: InformationSet, cell_size_m: float = BELIEF_CELL_SIZE_M
) -> np.ndarray:
    """Earliest *observed* burn time per belief cell; ``+inf`` where unobserved.

    Uses each detection's ``event_time_min`` -- the time of the state that was
    sampled -- and never its availability time, which is only about legality.
    """
    shape = _grid_shape(info, cell_size_m)
    out = np.full(shape, np.inf)
    det = info.fire_detections
    if det.get("x_m") is None or len(det["x_m"]) == 0:
        return out
    xs = det["x_m"].astype(float)
    ys = det["y_m"].astype(float)
    ts = det["event_time_min"].astype(float)
    j = np.clip((xs / cell_size_m).astype(int), 0, shape[1] - 1)
    i = np.clip((ys / cell_size_m).astype(int), 0, shape[0] - 1)
    for ii, jj, tt in zip(i, j, ts):
        if tt < out[ii, jj]:
            out[ii, jj] = tt
    return out


def forecast_hazard(
    info: InformationSet,
    forecast: Forecast | None,
    fallback_buffer_m: float,
    cell_size_m: float = BELIEF_CELL_SIZE_M,
) -> ArrivalTimeHazard:
    """Belief of a forecast-aware policy: observed fire, plus the forecast.

    The two are combined by element-wise minimum.  A policy that ignored what
    it had already *seen* in favour of a prediction would be a straw man; a
    real forecast-aware policy keeps both.

    When no forecast is usable yet, the belief degrades to the observed fire
    with ``fallback_buffer_m`` -- i.e. to a buffer policy.  That is what makes
    waiting a genuine trade-off rather than a free option.
    """
    observed = observed_arrival_estimate(info, cell_size_m)
    dist = distance_to_detections_m(info, cell_size_m)
    observed = np.minimum(observed, np.where(dist <= fallback_buffer_m, 0.0, np.inf))
    if forecast is None:
        return ArrivalTimeHazard(
            arrival_time_min=observed,
            cell_size_m=cell_size_m,
            source="OBSERVED_ONLY_NO_FORECAST",
        )
    if abs(forecast.cell_size_m - cell_size_m) > 1e-9:
        raise ValueError(
            "forecast grid and belief grid must match: "
            f"{forecast.cell_size_m} vs {cell_size_m}"
        )
    predicted = forecast.predicted_arrival_time_min
    if predicted.shape != observed.shape:
        raise ValueError(
            f"forecast shape {predicted.shape} != belief shape {observed.shape}"
        )
    return ArrivalTimeHazard(
        arrival_time_min=np.minimum(observed, predicted),
        cell_size_m=cell_size_m,
        source=forecast.forecast_id,
    )
