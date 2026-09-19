"""Raster geometry and terrain derivatives.

Coordinates are local metres: ``x`` east, ``y`` north, origin at the south-west
corner of cell ``(0, 0)``.  Array indexing is ``[i, j]`` = ``[row, col]`` =
``[y, x]``.  No map projection is modelled (``docs/ASSUMPTIONS.md#A-01``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import GridConfig


@dataclass(frozen=True)
class Grid:
    """Regular square raster geometry."""

    nx: int
    ny: int
    cell_size_m: float

    @classmethod
    def from_config(cls, cfg: GridConfig) -> "Grid":
        return cls(nx=int(cfg.nx), ny=int(cfg.ny), cell_size_m=float(cfg.cell_size_m))

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    @property
    def width_m(self) -> float:
        return self.nx * self.cell_size_m

    @property
    def height_m(self) -> float:
        return self.ny * self.cell_size_m

    @property
    def cell_area_m2(self) -> float:
        return self.cell_size_m**2

    def cell_centres(self) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(X, Y)`` cell-centre coordinate arrays of shape ``(ny, nx)``."""
        xs = (np.arange(self.nx) + 0.5) * self.cell_size_m
        ys = (np.arange(self.ny) + 0.5) * self.cell_size_m
        return np.meshgrid(xs, ys)

    def xy_to_ij(self, x_m: float, y_m: float) -> tuple[int, int]:
        """Cell containing ``(x_m, y_m)``, clipped to the domain."""
        j = int(np.clip(np.floor(x_m / self.cell_size_m), 0, self.nx - 1))
        i = int(np.clip(np.floor(y_m / self.cell_size_m), 0, self.ny - 1))
        return i, j

    def ij_to_xy(self, i: np.ndarray | int, j: np.ndarray | int):
        """Centre coordinates of cell(s) ``(i, j)``."""
        x = (np.asarray(j) + 0.5) * self.cell_size_m
        y = (np.asarray(i) + 0.5) * self.cell_size_m
        return x, y

    def contains(self, x_m: np.ndarray, y_m: np.ndarray) -> np.ndarray:
        """Boolean mask of points inside the domain."""
        return (
            (np.asarray(x_m) >= 0.0)
            & (np.asarray(x_m) < self.width_m)
            & (np.asarray(y_m) >= 0.0)
            & (np.asarray(y_m) < self.height_m)
        )


@dataclass(frozen=True)
class TerrainDerivatives:
    """Slope magnitude and upslope direction, per cell."""

    slope_rad: np.ndarray
    upslope_dir_rad: np.ndarray  # direction of steepest ASCENT, CCW from east


def terrain_derivatives(elevation_m: np.ndarray, cell_size_m: float) -> TerrainDerivatives:
    """Central-difference slope and upslope direction.

    ``numpy.gradient`` uses one-sided differences at the boundary, which is the
    documented behaviour (``docs/NATURE_MODEL.md#2``).

    Args:
        elevation_m: elevation raster, shape ``(ny, nx)``.
        cell_size_m: cell size in metres.

    Returns:
        :class:`TerrainDerivatives` with arrays of the same shape.
    """
    gy, gx = np.gradient(np.asarray(elevation_m, dtype=float), float(cell_size_m))
    slope = np.arctan(np.hypot(gx, gy))
    upslope = np.arctan2(gy, gx)
    return TerrainDerivatives(slope_rad=slope, upslope_dir_rad=upslope)
