"""Synthetic landscape: grid geometry, terrain and fuels.

Nothing here is derived from a real DEM or a real fuel map
(``docs/ASSUMPTIONS.md#A``).
"""

from .grid import Grid, TerrainDerivatives, terrain_derivatives
from .terrain import build_elevation
from .fuels import FuelField, build_fuels

__all__ = [
    "Grid",
    "TerrainDerivatives",
    "terrain_derivatives",
    "build_elevation",
    "FuelField",
    "build_fuels",
]
