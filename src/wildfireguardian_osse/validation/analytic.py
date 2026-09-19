"""Shape and rate metrics used by the validation worlds (``docs/VALIDATION.md``).

These are deliberately simple and measured from the hidden arrival-time field,
so a failure points at the nature model rather than at the metric.
"""

from __future__ import annotations

import numpy as np

from ..landscape.grid import Grid


def effective_speed_ratio(
    arrival_time_min: np.ndarray,
    grid: Grid,
    origin_ij: tuple[int, int],
    r_min_m: float,
    r_max_m: float,
) -> tuple[float, float, float]:
    """Spread-speed isotropy over an annulus around the ignition cell.

    Returns:
        ``(min_speed, max_speed, ratio)`` in m/min, where speed is
        ``r / T`` for every burned cell whose distance from the ignition cell
        centre lies in ``[r_min_m, r_max_m]``.  A perfectly isotropic model
        gives ``ratio == 1``; the 8-neighbour stencil gives about 1.13
        (``docs/VALIDATION.md#note-on-v1s-tolerance``).
    """
    X, Y = grid.cell_centres()
    cx, cy = grid.ij_to_xy(*origin_ij)
    r = np.hypot(X - cx, Y - cy)
    sel = (r >= r_min_m) & (r <= r_max_m) & np.isfinite(arrival_time_min) & (arrival_time_min > 0)
    if not np.any(sel):
        return (float("nan"), float("nan"), float("nan"))
    speed = r[sel] / arrival_time_min[sel]
    lo, hi = float(speed.min()), float(speed.max())
    return lo, hi, (hi / lo if lo > 0 else float("inf"))


def directional_extent(
    arrival_time_min: np.ndarray,
    grid: Grid,
    origin_ij: tuple[int, int],
    bearing_rad: float,
    half_angle_deg: float = 12.0,
) -> float:
    """Maximum burned distance from the ignition cell within a bearing sector."""
    X, Y = grid.cell_centres()
    cx, cy = grid.ij_to_xy(*origin_ij)
    dx, dy = X - cx, Y - cy
    r = np.hypot(dx, dy)
    ang = np.arctan2(dy, dx)
    delta = np.abs((ang - bearing_rad + np.pi) % (2 * np.pi) - np.pi)
    sel = np.isfinite(arrival_time_min) & (delta <= np.deg2rad(half_angle_deg)) & (r > 0)
    return float(r[sel].max()) if np.any(sel) else 0.0


def burned_centroid(
    arrival_time_min: np.ndarray, grid: Grid, t_min: float | None = None
) -> tuple[float, float]:
    """Centroid of the burned set (optionally at a time ``t_min``)."""
    X, Y = grid.cell_centres()
    mask = np.isfinite(arrival_time_min)
    if t_min is not None:
        mask &= arrival_time_min <= t_min
    if not np.any(mask):
        return (float("nan"), float("nan"))
    return float(X[mask].mean()), float(Y[mask].mean())


def principal_axis_deg(
    arrival_time_min: np.ndarray,
    grid: Grid,
    t_lo: float,
    t_hi: float,
) -> float:
    """Orientation of the cells that burned in ``(t_lo, t_hi]``, degrees CCW from east.

    Computed as the direction from the centroid of everything burned by
    ``t_lo`` to the centroid of what burned during the window -- a robust
    "which way did the fire grow" measure that does not depend on the shape
    being elliptical.  Returns ``nan`` if the window burned nothing.
    """
    X, Y = grid.cell_centres()
    before = np.isfinite(arrival_time_min) & (arrival_time_min <= t_lo)
    window = np.isfinite(arrival_time_min) & (arrival_time_min > t_lo) & (
        arrival_time_min <= t_hi
    )
    if not np.any(window) or not np.any(before):
        return float("nan")
    dx = float(X[window].mean() - X[before].mean())
    dy = float(Y[window].mean() - Y[before].mean())
    return float(np.rad2deg(np.arctan2(dy, dx)) % 360.0)
