"""Assembly of one hidden nature world.

Synthetic nature model for controlled experiments; not an operational wildfire
forecast model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import GENERATOR_VERSION, MODEL_BANNER
from ..config import ScenarioConfig
from ..landscape import (
    FuelField,
    Grid,
    TerrainDerivatives,
    build_elevation,
    build_fuels,
    terrain_derivatives,
)
from ..rng import SeedRegistry
from ..weather import WeatherSeries, build_weather
from .ros import RosCoefficients, RosField, build_ros_field
from .spotting import SpotEvent, SpottingProcess
from .spread import SpreadResult, propagate

#: Warn above this Courant number ``max(R)*dt/dx``.  Measured on a uniform
#: landscape: at 0.55 the arrival-time field matches a 4x finer step to within
#: a mean of 0.1 min (IoU 0.998); at 1.36 the mean gap is 8.7 min (IoU 0.943).
#: One cell per step is where the sub-step interpolation stops being adequate.
COURANT_WARN_THRESHOLD = 1.0

#: Below this many cells of sideways (flank) travel over the horizon, the
#: raster cannot carry the flank of an elongated fire and the burned area is
#: materially under-predicted.  Above this eccentricity the stencil's angular
#: staircase error dominates even when the flank is resolved.  Both thresholds
#: come from the measured accuracy table in ``docs/VALIDATION.md#5``.
FLANK_CELLS_WARN_THRESHOLD = 8.0
ECCENTRICITY_WARN_THRESHOLD = 0.94


@dataclass
class NatureTruth:
    """Everything the hidden world knows.  Never planner-visible."""

    grid: Grid
    elevation_m: np.ndarray
    fuels: FuelField
    terrain: TerrainDerivatives
    weather: WeatherSeries
    arrival_time_min: np.ndarray
    spread: SpreadResult
    initial_ignitions: list[dict[str, float]]
    spot_events: list[SpotEvent]
    params: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def burned_mask_final(self) -> np.ndarray:
        return np.isfinite(self.arrival_time_min)

    def active_mask(self, t_min: float, residence_time_min: float) -> np.ndarray:
        """Cells flaming at ``t_min`` -- the only thing a fire sensor can see."""
        return (self.arrival_time_min <= t_min) & (
            self.arrival_time_min > t_min - residence_time_min
        )

    def burned_area_ha(self) -> float:
        return float(np.count_nonzero(self.burned_mask_final)) * self.grid.cell_area_m2 / 1e4


def simulate_nature(cfg: ScenarioConfig, seeds: SeedRegistry) -> NatureTruth:
    """Generate the hidden world for one scenario.

    Args:
        cfg: the scenario configuration.
        seeds: the world's derived random streams.

    Returns:
        A fully populated :class:`NatureTruth`.

    Note:
        Landscape randomness uses the ``nature_seed`` sub-streams ``terrain``
        and ``fuels``; weather uses ``weather_seed``; spotting uses
        ``spotting_seed``.  Nothing here touches ``sensor_seed`` or
        ``missingness_seed``, which is why the observation configuration
        provably cannot change the truth
        (``tests/test_determinism.py::test_stream_independence``).
    """
    grid = Grid.from_config(cfg.grid)

    elevation = build_elevation(cfg.terrain, grid, seeds.generator("nature_seed", "terrain"))
    terrain = terrain_derivatives(elevation, grid.cell_size_m)
    fuels = build_fuels(cfg.fuels, grid, seeds.generator("nature_seed", "fuels"))
    weather = build_weather(cfg.weather, cfg.time, seeds)

    coeffs = RosCoefficients.from_config(cfg.nature)
    r0 = cfg.nature.r0_base_m_per_min * cfg.nature.spread_multiplier * fuels.multiplier
    slope_factor = coeffs.slope_factor(terrain.slope_rad)

    cache: dict[tuple[float, float], RosField] = {}

    def ros_at(t_min: float) -> RosField:
        speed, direction, _, _ = weather.at(t_min)
        key = (round(speed, 9), round(direction, 9))
        cached = cache.get(key)
        if cached is None:
            cached = build_ros_field(
                r0, slope_factor, terrain.upslope_dir_rad, speed, direction, coeffs
            )
            # Constant-wind scenarios reuse a single field; a fluctuating wind
            # would otherwise grow this without bound.
            if len(cache) > 4096:
                cache.clear()
            cache[key] = cached
        return cached

    arrival = np.full(grid.shape, np.inf, dtype=float)
    initial: list[dict[str, float]] = []
    for ig in cfg.nature.ignitions:
        i, j = grid.xy_to_ij(ig.x_m, ig.y_m)
        ignitable = bool(fuels.burnable[i, j])
        if ignitable:
            arrival[i, j] = min(float(arrival[i, j]), float(ig.time_min))
        initial.append(
            {
                "x_m": float(ig.x_m),
                "y_m": float(ig.y_m),
                "time_min": float(ig.time_min),
                "cell_i": int(i),
                "cell_j": int(j),
                "ignited": ignitable,
                "reason": "ignited" if ignitable else "nonburnable_cell",
            }
        )

    spotting = SpottingProcess(
        cfg=cfg.nature.spotting,
        grid=grid,
        burnable=fuels.burnable,
        fuel_multiplier=fuels.multiplier,
        wind_dir_at=lambda t: weather.at(t)[1],
        residence_time_min=cfg.nature.residence_time_min,
        # A generator is built even when spotting is disabled, but it is never
        # drawn from: SpottingProcess.step returns immediately.
        rng=seeds.generator("spotting_seed"),
    )

    result = propagate(
        arrival_time_min=arrival,
        burnable=fuels.burnable,
        ros_at=ros_at,
        cell_size_m=grid.cell_size_m,
        dt_min=cfg.time.dt_min,
        horizon_min=cfg.time.horizon_min,
        residence_time_min=cfg.nature.residence_time_min,
        stencil_max_offset=cfg.nature.stencil_max_offset,
        step_hook=spotting.step if cfg.nature.spotting.enabled else None,
    )

    flags: list[str] = []
    warnings: list[str] = []
    if not np.any(np.isfinite(arrival)):
        flags.append("degenerate_no_ignition")
    if result.boundary_contact:
        flags.append("boundary_contact")
    if result.max_courant > COURANT_WARN_THRESHOLD:
        warnings.append(
            f"max_courant={result.max_courant:.2f} exceeds "
            f"{COURANT_WARN_THRESHOLD}: the front crosses more than one cell "
            "per step, so arrival times are interpolation-limited; reduce "
            "time.dt_min or increase grid.cell_size_m (docs/NATURE_MODEL.md#4)"
        )
    if result.flank_cells_at_horizon < FLANK_CELLS_WARN_THRESHOLD:
        warnings.append(
            f"flank_cells_at_horizon={result.flank_cells_at_horizon:.1f} is "
            f"below {FLANK_CELLS_WARN_THRESHOLD}: the fire is too narrow for "
            "this cell size, so the burned area is under-predicted "
            "(docs/VALIDATION.md#5)"
        )
    if result.max_eccentricity > ECCENTRICITY_WARN_THRESHOLD:
        warnings.append(
            f"max_eccentricity={result.max_eccentricity:.3f} exceeds "
            f"{ECCENTRICITY_WARN_THRESHOLD}: the stencil's angular error "
            "dominates at this elongation and the burned area is "
            "under-predicted (docs/VALIDATION.md#5)"
        )

    params: dict[str, Any] = {
        "model_banner": MODEL_BANNER,
        "generator_version": GENERATOR_VERSION,
        "r0_base_m_per_min": cfg.nature.r0_base_m_per_min,
        "spread_multiplier": cfg.nature.spread_multiplier,
        "residence_time_min": cfg.nature.residence_time_min,
        "ros_coefficients": {
            "wind_coeff_a": coeffs.wind_coeff_a,
            "wind_exp_b": coeffs.wind_exp_b,
            "slope_coeff_a": coeffs.slope_coeff_a,
            "lb_coeff_c": coeffs.lb_coeff_c,
            "lb_exp_p": coeffs.lb_exp_p,
        },
        "terrain": {k: v for k, v in vars(cfg.terrain).items()},
        "fuels": {k: v for k, v in vars(cfg.fuels).items()},
        "spotting": {k: v for k, v in vars(cfg.nature.spotting).items()},
        "max_courant": result.max_courant,
        "stencil_max_offset": cfg.nature.stencil_max_offset,
        "flank_cells_at_horizon": result.flank_cells_at_horizon,
        "max_eccentricity": result.max_eccentricity,
        "seeds": seeds.as_dict(),
    }

    return NatureTruth(
        grid=grid,
        elevation_m=elevation,
        fuels=fuels,
        terrain=terrain,
        weather=weather,
        arrival_time_min=arrival,
        spread=result,
        initial_ignitions=initial,
        spot_events=spotting.events,
        params=params,
        flags=flags,
        warnings=warnings,
    )
