"""Mode A -- ``CONTROLLED_PERTURBATION`` forecasts.

Structured, coherent degradations of the hidden arrival field.  **IID pixel
noise is not offered**: it is not how forecasts are wrong, and it would make
errors average out over a region instead of displacing a front.

This mode is **derived from hidden truth by construction**.  It is therefore a
*mechanism probe*, not a leakage-safe planner, and at zero error with zero
latency it is the oracle reference.  It runs evaluator-side, outside any
planner sandbox; the policy only ever receives the resulting
:class:`~.forecast.Forecast`.
"""

from __future__ import annotations

import numpy as np

from ..landscape.grid import Grid
from .forecast import ErrorRegime, Forecast, ForecastProvenance
from .sandbox import assert_evaluator_context

#: Nominal rate used to bound the region a spot ignition could have seeded when
#: `missed_spotting` removes it.  Approximate by construction.
SPOT_ATTRIBUTION_RATE_M_PER_MIN = 25.0


def _warp(
    arrival_time_min: np.ndarray,
    grid: Grid,
    origin_xy_m: tuple[float, float],
    angle_rad: float,
    shift_m: tuple[float, float],
) -> np.ndarray:
    """Rotate about ``origin`` and translate, by inverse nearest-neighbour lookup.

    The whole field moves together, which is the point: a real forecast is
    wrong about *where the fire is going*, coherently, not cell by cell.
    """
    X, Y = grid.cell_centres()
    ox, oy = origin_xy_m
    # predicted(p) = truth( R(-angle) . (p - shift - origin) + origin )
    px = X - shift_m[0] - ox
    py = Y - shift_m[1] - oy
    cos_a, sin_a = np.cos(-angle_rad), np.sin(-angle_rad)
    sx = cos_a * px - sin_a * py + ox
    sy = sin_a * px + cos_a * py + oy

    cols = np.floor(sx / grid.cell_size_m).astype(int)
    rows = np.floor(sy / grid.cell_size_m).astype(int)
    inside = (rows >= 0) & (rows < grid.ny) & (cols >= 0) & (cols < grid.nx)
    out = np.full(arrival_time_min.shape, np.inf, dtype=float)
    out[inside] = arrival_time_min[rows[inside], cols[inside]]
    return out


def _apply_rate_bias(
    arrival_time_min: np.ndarray, issue_time_min: float, rate_bias: float
) -> np.ndarray:
    """Persistent under/over-prediction of spread rate after the issue time.

    ``rate_bias > 1`` predicts a faster fire (earlier arrivals);
    ``rate_bias < 1`` a slower one.  Times already past at issue are untouched.
    """
    if rate_bias == 1.0:
        return arrival_time_min
    out = arrival_time_min.copy()
    future = np.isfinite(out) & (out > issue_time_min)
    out[future] = issue_time_min + (out[future] - issue_time_min) / float(rate_bias)
    return out


def _remove_spotting(
    arrival_time_min: np.ndarray, grid: Grid, spot_events, issue_time_min: float
) -> np.ndarray:
    """Drop the ground a future spot ignition seeded.

    Approximate: for each spot that ignites after the issue time, cells are
    removed when they arrive after the spot and lie within the distance a fire
    could have covered from it.  The approximation is documented rather than
    hidden -- it over-removes where a spot merged into the main front.
    """
    out = arrival_time_min.copy()
    X, Y = grid.cell_centres()
    for event in spot_events:
        if not getattr(event, "ignited", False):
            continue
        t_spot = float(event.time_min)
        if t_spot < issue_time_min:
            continue  # already observable by issue time; not a *future* spot
        distance = np.hypot(X - event.land_x_m, Y - event.land_y_m)
        reachable = distance <= np.maximum(out - t_spot, 0.0) * SPOT_ATTRIBUTION_RATE_M_PER_MIN
        out[np.isfinite(out) & (out >= t_spot) & reachable] = np.inf
    return out


def make_controlled_perturbation_forecast(
    *,
    truth_arrival_min: np.ndarray,
    grid: Grid,
    origin_xy_m: tuple[float, float],
    issue_time_min: float,
    horizon_min: float,
    regime: ErrorRegime,
    latency_min: float,
    spot_events=(),
) -> Forecast:
    """Build a Mode A forecast.

    Args:
        truth_arrival_min: the hidden arrival-time field.  Evaluator-only.
        grid: raster geometry.
        origin_xy_m: point the directional bias rotates about (the ignition).
        issue_time_min: when the forecast is produced.
        horizon_min: how far ahead it is valid.
        regime: the declared error regime.
        latency_min: delay before the forecast becomes usable.
        spot_events: truth-side spotting record, used only by `missed_spotting`.

    Returns:
        A :class:`Forecast` whose ``arrival_time_min`` is the degraded field.

    Raises:
        TruthAccessViolation: if called from inside a planner sandbox.
    """
    assert_evaluator_context("controlled-perturbation forecast (reads hidden truth)")

    field = np.asarray(truth_arrival_min, dtype=float)
    if regime.direction_bias_deg or regime.spatial_shift_m:
        # The displacement is applied along the fire's own downwind axis by
        # rotating first, so direction bias and shift compose coherently.
        angle = np.deg2rad(regime.direction_bias_deg)
        shift = (
            regime.spatial_shift_m * np.cos(angle),
            regime.spatial_shift_m * np.sin(angle),
        )
        field = _warp(field, grid, origin_xy_m, angle, shift)
    field = _apply_rate_bias(field, issue_time_min, regime.rate_bias)
    if regime.missed_spotting:
        field = _remove_spotting(field, grid, spot_events, issue_time_min)

    return Forecast(
        arrival_time_min=field,
        issue_time_min=float(issue_time_min),
        availability_time_min=float(issue_time_min) + float(latency_min),
        valid_from_min=float(issue_time_min),
        valid_to_min=float(issue_time_min) + float(horizon_min),
        provenance=ForecastProvenance.CONTROLLED_PERTURBATION,
        error_regime=regime,
        diagnostics={"origin_xy_m": [float(origin_xy_m[0]), float(origin_xy_m[1])]},
    )
