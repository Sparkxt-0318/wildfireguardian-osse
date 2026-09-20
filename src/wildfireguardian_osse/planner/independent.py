"""Mode B -- ``INDEPENDENT_MODEL_FORECAST``.

A structurally different, simplified prediction model that consumes ``D_s`` and
nothing else.  It never sees the nature model, its parameters, its seeds or its
state.  This is the mode the flagship conclusions rely on.

How it differs from nature, structurally and not merely in its parameters:

| | nature | this planner model |
|---|---|---|
| geometry | 16-direction raster front | one analytic ellipse |
| fuel | heterogeneous multiplier field | none |
| terrain | slope vector combined with wind | none |
| wind | time-varying, AR(1) about a schedule | one estimate, persisted |
| rate law | `R0(1 + a·U^1.5)`, power law | `r0 + k·U`, linear |
| shape law | `LB = 1 + 0.07·phi^1.5` | `LB = 1 + 0.2·U`, linear |
| spotting | stochastic firebrands | none |

It is therefore wrong in ways nobody chose: its errors come from the model gap
and from the observations it was given, not from a knob.
"""

from __future__ import annotations

import numpy as np

from ..landscape.grid import Grid
from .estimate import estimate_fire_state, estimate_wind
from .forecast import ErrorRegime, Forecast, ForecastProvenance
from .view import AvailableData

#: Planner-side rate law.  Linear in wind speed, deliberately unlike nature's.
PLANNER_BASE_RATE_M_PER_MIN = 2.5
PLANNER_WIND_GAIN = 2.2
#: Planner-side shape law.  Also linear, also deliberately unlike nature's.
PLANNER_LB_GAIN = 0.20
PLANNER_MAX_LB = 4.0


def _planner_ellipse(wind_speed_ms: float) -> tuple[float, float]:
    """Return ``(head_rate_m_per_min, eccentricity)`` under the planner's law."""
    head = PLANNER_BASE_RATE_M_PER_MIN + PLANNER_WIND_GAIN * max(0.0, wind_speed_ms)
    lb = min(PLANNER_MAX_LB, 1.0 + PLANNER_LB_GAIN * max(0.0, wind_speed_ms))
    ecc = float(np.sqrt(max(lb * lb - 1.0, 0.0)) / lb)
    return float(head), ecc


def make_independent_model_forecast(
    *,
    data: AvailableData,
    grid: Grid,
    issue_time_min: float,
    horizon_min: float,
    latency_min: float,
    regime: ErrorRegime | None = None,
) -> Forecast | None:
    """Build a Mode B forecast from available observations only.

    Args:
        data: ``D_s``.
        grid: raster geometry (static context; not truth).
        issue_time_min: the information time this forecast is issued at.
        horizon_min: how far ahead to predict.
        latency_min: delay before it becomes usable.
        regime: recorded for provenance; Mode B applies **no** artificial
            degradation, so only its name is used.

    Returns:
        A :class:`Forecast`, or ``None`` when the available data do not support
        one -- which is itself a result: early on, the planner simply cannot
        forecast, and the policy must cope.
    """
    fire = estimate_fire_state(data)
    if not fire.valid:
        return None
    wind = estimate_wind(data)
    speed = wind.speed_ms if wind.valid else 0.0
    heading = wind.dir_rad if wind.valid else 0.0

    head_rate, ecc = _planner_ellipse(speed)

    X, Y = grid.cell_centres()
    dx = X - fire.centroid_x_m
    dy = Y - fire.centroid_y_m
    distance = np.hypot(dx, dy)
    # Distance from the estimated burning edge, not from its centre.
    outward = np.maximum(distance - fire.radius_m, 0.0)

    bearing = np.arctan2(dy, dx)
    rate = head_rate * (1.0 - ecc) / (1.0 - ecc * np.cos(bearing - heading))
    rate = np.maximum(rate, 1e-6)

    # The state is as of the newest detection, which is older than the issue
    # time: the planner propagates from what it last saw, not from "now".
    state_time = float(fire.state_time_min)
    predicted = state_time + outward / rate
    predicted[distance <= fire.radius_m] = state_time

    valid_to = float(issue_time_min) + float(horizon_min)
    predicted[predicted > valid_to] = np.inf
    # A forecast describes times at or after its issue time; anything the model
    # places in the past is reported as "already burning at issue".
    predicted[np.isfinite(predicted) & (predicted < issue_time_min)] = float(issue_time_min)

    return Forecast(
        arrival_time_min=predicted,
        issue_time_min=float(issue_time_min),
        availability_time_min=float(issue_time_min) + float(latency_min),
        valid_from_min=float(issue_time_min),
        valid_to_min=valid_to,
        provenance=ForecastProvenance.INDEPENDENT_MODEL_FORECAST,
        error_regime=regime if regime is not None else ErrorRegime("independent_model"),
        diagnostics={
            "estimated_centroid_x_m": fire.centroid_x_m,
            "estimated_centroid_y_m": fire.centroid_y_m,
            "estimated_radius_m": fire.radius_m,
            "n_detections_used": fire.n_detections,
            "state_time_min": state_time,
            "estimated_wind_speed_ms": speed,
            "estimated_wind_dir_deg": float(np.rad2deg(heading) % 360.0),
            "planner_head_rate_m_per_min": head_rate,
            "planner_eccentricity": ecc,
        },
    )
