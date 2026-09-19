"""Synthetic elevation fields.

Four kinds, all synthetic (``docs/ASSUMPTIONS.md#A-05``):

``flat``   constant elevation -- the control case, zero slope everywhere.
``plane``  a uniform planar slope, the analytically cleanest slope test.
``ridge``  a Gaussian ridge across the domain: slope reverses sign, so a fire
           can run upslope and then downslope.
``noise``  smoothed value noise, for heterogeneous terrain.
"""

from __future__ import annotations

import numpy as np

from ..config import TerrainConfig
from .grid import Grid


def _smooth(field: np.ndarray, sigma_cells: float) -> np.ndarray:
    """Separable box-blur repeated three times ~ Gaussian smoothing.

    Implemented locally to avoid a SciPy dependency (``docs/SCOPE.md``).
    Deterministic and shape-preserving.
    """
    if sigma_cells <= 0.5:
        return field
    radius = max(1, int(round(sigma_cells)))
    kernel = np.ones(2 * radius + 1, dtype=float) / (2 * radius + 1)
    out = field.astype(float)
    for _ in range(3):
        padded = np.pad(out, ((0, 0), (radius, radius)), mode="edge")
        out = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), 1, padded)
        padded = np.pad(out, ((radius, radius), (0, 0)), mode="edge")
        out = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), 0, padded)
    return out


def build_elevation(
    cfg: TerrainConfig, grid: Grid, rng: np.random.Generator
) -> np.ndarray:
    """Build the elevation raster in metres.

    Args:
        cfg: terrain configuration.
        grid: raster geometry.
        rng: generator from the ``nature_seed`` stream.  Consumed **only** by
            ``kind='noise'``, so switching terrain kinds does not shift the
            stream for the other kinds.

    Returns:
        Elevation raster, shape ``(ny, nx)``, dtype float64.
    """
    X, Y = grid.cell_centres()
    base = float(cfg.base_elevation_m)

    if cfg.kind == "flat":
        return np.full(grid.shape, base, dtype=float)

    if cfg.kind == "plane":
        # A plane whose direction of steepest ascent is aspect_deg (CCW from
        # east) and whose slope magnitude is exactly slope_deg.
        theta = np.deg2rad(cfg.aspect_deg)
        grad = np.tan(np.deg2rad(cfg.slope_deg))
        return base + grad * (np.cos(theta) * X + np.sin(theta) * Y)

    if cfg.kind == "ridge":
        theta = np.deg2rad(cfg.aspect_deg)
        # signed distance from the domain centre along the aspect direction
        cx, cy = grid.width_m / 2.0, grid.height_m / 2.0
        s = np.cos(theta) * (X - cx) + np.sin(theta) * (Y - cy)
        return base + cfg.relief_m * np.exp(-0.5 * (s / cfg.ridge_width_m) ** 2)

    if cfg.kind == "noise":
        sigma_cells = cfg.noise_scale_m / grid.cell_size_m
        raw = rng.standard_normal(grid.shape)
        smoothed = _smooth(raw, sigma_cells)
        spread = float(np.ptp(smoothed))
        if spread <= 0:  # pragma: no cover - degenerate tiny grids
            return np.full(grid.shape, base, dtype=float)
        normalised = (smoothed - smoothed.min()) / spread
        return base + cfg.relief_m * normalised

    raise ValueError(f"unhandled terrain kind {cfg.kind!r}")  # pragma: no cover
