"""Current-state estimators built from ``D_s`` alone.

Shared by the tuned baseline and the independent forecast model, deliberately:
the baseline must not be handicapped by a worse view of the present than the
forecast-aware policy has.  Any difference in their behaviour then comes from
what they do with the same estimate, which is the comparison the experiment is
actually about.

A current-state estimate is **not** a forecast
(``experiments/forecast_value_mve/PROTOCOL.md`` section 5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .view import AvailableData

#: Weight given to each reported confidence level.  Confidence is a coarse
#: observation, not the hidden detection probability.
CONFIDENCE_WEIGHT = {"high": 1.0, "nominal": 0.7, "low": 0.4}

#: Detections older than this (relative to the newest available) are ignored:
#: they describe where the fire *was*.
DETECTION_WINDOW_MIN = 45.0

#: Station records older than this are ignored when estimating wind.
WEATHER_WINDOW_MIN = 30.0


@dataclass(frozen=True)
class FireStateEstimate:
    """Where the planner believes the fire is now."""

    valid: bool
    centroid_x_m: float = float("nan")
    centroid_y_m: float = float("nan")
    radius_m: float = 0.0
    n_detections: int = 0
    state_time_min: float = float("nan")
    spread_m: float = 0.0

    def distance_to(self, x_m: float, y_m: float) -> float:
        """Distance from the estimated fire edge to a point; 0 if inside."""
        if not self.valid:
            return float("inf")
        d = float(np.hypot(x_m - self.centroid_x_m, y_m - self.centroid_y_m))
        return max(0.0, d - self.radius_m)


@dataclass(frozen=True)
class WindEstimate:
    """What the planner believes the wind is doing."""

    valid: bool
    speed_ms: float = 0.0
    dir_rad: float = 0.0
    n_records: int = 0


def estimate_fire_state(data: AvailableData) -> FireStateEstimate:
    """Estimate the current fire from available detections.

    False positives are **not** labelled in the planner-facing file, so they are
    not filtered here either; they pull the estimate around exactly as they
    would in reality (``docs/DECISIONS.md#d-007``).
    """
    table = data.fire_detections
    if not table or len(table.get("obs_id", [])) == 0:
        return FireStateEstimate(valid=False)

    event = np.asarray(table["event_time_min"], dtype=float)
    newest = float(event.max())
    recent = event >= newest - DETECTION_WINDOW_MIN
    if not np.any(recent):
        return FireStateEstimate(valid=False)

    x = np.asarray(table["x_m"], dtype=float)[recent]
    y = np.asarray(table["y_m"], dtype=float)[recent]
    confidence = [str(c) for c in np.asarray(table["confidence"])[recent]]
    weights = np.array([CONFIDENCE_WEIGHT.get(c, 0.5) for c in confidence], dtype=float)
    total = float(weights.sum())
    if total <= 0:
        return FireStateEstimate(valid=False)

    cx = float((x * weights).sum() / total)
    cy = float((y * weights).sum() / total)
    distances = np.hypot(x - cx, y - cy)
    # Footprint-aware radius: a single detection still implies a pixel of fire.
    pixel = float(np.asarray(table["pixel_size_m"], dtype=float)[recent].mean())
    radius = float(max(distances.max(), 0.5 * pixel))
    return FireStateEstimate(
        valid=True,
        centroid_x_m=cx,
        centroid_y_m=cy,
        radius_m=radius,
        n_detections=int(np.count_nonzero(recent)),
        state_time_min=newest,
        spread_m=float(distances.std()) if distances.size > 1 else 0.0,
    )


def estimate_wind(data: AvailableData) -> WindEstimate:
    """Vector-mean wind over the recent available station records."""
    table = data.weather_observations
    if not table or len(table.get("obs_id", [])) == 0:
        return WindEstimate(valid=False)

    event = np.asarray(table["event_time_min"], dtype=float)
    newest = float(event.max())
    recent = event >= newest - WEATHER_WINDOW_MIN
    if not np.any(recent):
        return WindEstimate(valid=False)

    speed = np.asarray(table["wind_speed_ms"], dtype=float)[recent]
    direction = np.deg2rad(np.asarray(table["wind_dir_deg"], dtype=float)[recent])
    vx = float(np.mean(speed * np.cos(direction)))
    vy = float(np.mean(speed * np.sin(direction)))
    return WindEstimate(
        valid=True,
        speed_ms=float(np.hypot(vx, vy)),
        dir_rad=float(np.arctan2(vy, vx)),
        n_records=int(np.count_nonzero(recent)),
    )
