"""Synthetic fuel fields.

A fuel field is two rasters:

``multiplier``  continuous, dimensionless scaling of the base rate of spread.
                ``0`` is strictly non-burnable.  **Hidden model parameter.**
``fuel_class``  a coarse integer label.  **Planner-visible static context**
                (``docs/DECISIONS.md#d-006``).

The class is deliberately a quantisation of the multiplier: a planner knows
roughly what is burning where, but not the number the model actually uses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import FuelsConfig
from .grid import Grid
from .terrain import _smooth

#: Class 0 is reserved for strictly non-burnable cells.
NONBURNABLE_CLASS = 0


@dataclass(frozen=True)
class FuelField:
    multiplier: np.ndarray  # hidden
    fuel_class: np.ndarray  # planner-visible static context

    @property
    def burnable(self) -> np.ndarray:
        return self.multiplier > 0.0


def _quantise(multiplier: np.ndarray, n_classes: int) -> np.ndarray:
    """Quantise the continuous multiplier into coarse integer classes.

    Non-burnable cells become :data:`NONBURNABLE_CLASS`; burnable cells are
    spread over classes ``1 .. n_classes-1`` by equal-width binning of the
    burnable range.  Constant burnable fields collapse to class 1.
    """
    out = np.zeros(multiplier.shape, dtype=np.int16)
    burnable = multiplier > 0.0
    if not np.any(burnable):
        return out
    vals = multiplier[burnable]
    lo, hi = float(vals.min()), float(vals.max())
    n_burn = max(1, int(n_classes) - 1)
    if hi <= lo:
        out[burnable] = 1
        return out
    idx = np.floor((vals - lo) / (hi - lo) * n_burn).astype(int)
    out[burnable] = np.clip(idx, 0, n_burn - 1) + 1
    return out


def build_fuels(
    cfg: FuelsConfig, grid: Grid, rng: np.random.Generator
) -> FuelField:
    """Build the fuel field.

    Args:
        cfg: fuel configuration.
        grid: raster geometry.
        rng: generator from the ``nature_seed`` stream.  Consumed **only** by
            ``kind='patchy'``.

    Returns:
        A :class:`FuelField`.
    """
    X, Y = grid.cell_centres()
    mult = np.full(grid.shape, float(cfg.base_multiplier), dtype=float)

    if cfg.kind == "uniform":
        pass

    elif cfg.kind == "band":
        # A barrier band across the domain.  With band_multiplier = 0 this is a
        # hard, analytically checkable obstacle (validation world V4).
        if cfg.band_orientation == "vertical":
            coord, extent = X, grid.width_m
        else:
            coord, extent = Y, grid.height_m
        centre = cfg.band_position_frac * extent
        half = cfg.band_width_m / 2.0
        band = np.abs(coord - centre) <= half
        mult[band] = float(cfg.band_multiplier)

    elif cfg.kind == "patchy":
        sigma_cells = cfg.patch_scale_m / grid.cell_size_m
        raw = _smooth(rng.standard_normal(grid.shape), sigma_cells)
        spread = float(np.ptp(raw))
        if spread <= 0:  # pragma: no cover
            norm = np.full(grid.shape, 0.5)
        else:
            norm = (raw - raw.min()) / spread
        mult = cfg.base_multiplier * (
            cfg.patch_low + (cfg.patch_high - cfg.patch_low) * norm
        )

    else:  # pragma: no cover - guarded by config validation
        raise ValueError(f"unhandled fuels kind {cfg.kind!r}")

    mult = np.maximum(mult, 0.0)
    return FuelField(multiplier=mult, fuel_class=_quantise(mult, cfg.n_classes))
