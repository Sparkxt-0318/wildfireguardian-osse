"""Configuration schema for a scenario.

Every knob of the laboratory lives here, with a default, so that a scenario
file states only what it changes.  Unknown keys are a hard error: a typo in a
YAML file must never be silently ignored, because a silently-ignored knob is a
silently-invalid experiment.

Angle convention (also stated in ``AGENTS.md#4``): ``*_dir_deg`` is the
direction something points **toward**, measured counter-clockwise from east
(mathematical convention).  It is *not* meteorological "direction from".
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


class ConfigError(ValueError):
    """Raised for any malformed or inconsistent scenario configuration."""


# --------------------------------------------------------------------------
# strict construction helpers
# --------------------------------------------------------------------------

def _require_mapping(data: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ConfigError(f"{path}: expected a mapping, got {type(data).__name__}")
    return data


def _build(cls: type, data: Any, path: str):
    """Build a config dataclass, rejecting unknown keys.

    Nested dataclasses are declared per class in ``_NESTED`` (name -> class) and
    ``_NESTED_LIST`` (name -> element class) rather than by introspecting type
    annotations, which are strings under ``from __future__ import annotations``.
    """
    data = _require_mapping(data, path)
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) {unknown}. Allowed keys: {sorted(names)}"
        )
    nested: Mapping[str, type] = getattr(cls, "_NESTED", {})
    nested_list: Mapping[str, type] = getattr(cls, "_NESTED_LIST", {})
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        sub = f"{path}.{key}"
        if key in nested:
            kwargs[key] = _build(nested[key], value, sub)
        elif key in nested_list:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise ConfigError(f"{sub}: expected a list")
            kwargs[key] = [
                _build(nested_list[key], v, f"{sub}[{i}]") for i, v in enumerate(value)
            ]
        else:
            kwargs[key] = value
    try:
        return cls(**kwargs)
    except TypeError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"{path}: {exc}") from exc


def _positive(value: float, name: str) -> None:
    if not (float(value) > 0):
        raise ConfigError(f"{name} must be > 0, got {value!r}")


def _non_negative(value: float, name: str) -> None:
    if not (float(value) >= 0):
        raise ConfigError(f"{name} must be >= 0, got {value!r}")


def _probability(value: float, name: str) -> None:
    if not (0.0 <= float(value) <= 1.0):
        raise ConfigError(f"{name} must lie in [0, 1], got {value!r}")


def _one_of(value: str, allowed: Sequence[str], name: str) -> None:
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {list(allowed)}, got {value!r}")


# --------------------------------------------------------------------------
# landscape and time
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GridConfig:
    """Regular square raster.  ``x`` is east, ``y`` is north."""

    nx: int = 128
    ny: int = 128
    cell_size_m: float = 30.0

    def __post_init__(self) -> None:
        if self.nx < 4 or self.ny < 4:
            raise ConfigError("grid.nx and grid.ny must be >= 4")
        _positive(self.cell_size_m, "grid.cell_size_m")

    @property
    def width_m(self) -> float:
        return self.nx * self.cell_size_m

    @property
    def height_m(self) -> float:
        return self.ny * self.cell_size_m

    @property
    def cell_area_m2(self) -> float:
        return self.cell_size_m**2


@dataclass(frozen=True)
class TimeConfig:
    """Simulation time window, in minutes since scenario ``t0``."""

    horizon_min: float = 240.0
    dt_min: float = 1.0

    def __post_init__(self) -> None:
        _positive(self.horizon_min, "time.horizon_min")
        _positive(self.dt_min, "time.dt_min")
        if self.dt_min > self.horizon_min:
            raise ConfigError("time.dt_min must not exceed time.horizon_min")

    @property
    def n_steps(self) -> int:
        return int(round(self.horizon_min / self.dt_min))


@dataclass(frozen=True)
class TerrainConfig:
    """Synthetic terrain.  Not derived from any real DEM."""

    kind: str = "flat"
    base_elevation_m: float = 200.0
    slope_deg: float = 0.0
    aspect_deg: float = 0.0  # direction of steepest ASCENT, CCW from east
    relief_m: float = 150.0
    ridge_width_m: float = 900.0
    noise_scale_m: float = 600.0

    def __post_init__(self) -> None:
        _one_of(self.kind, ("flat", "plane", "ridge", "noise"), "terrain.kind")
        if not (0.0 <= self.slope_deg < 80.0):
            raise ConfigError("terrain.slope_deg must lie in [0, 80)")
        _positive(self.ridge_width_m, "terrain.ridge_width_m")
        _positive(self.noise_scale_m, "terrain.noise_scale_m")


@dataclass(frozen=True)
class FuelsConfig:
    """Synthetic fuels: a spread multiplier field plus a coarse class label.

    ``base_multiplier`` scales the base rate of spread.  ``0`` is strictly
    non-burnable.  The continuous multiplier is **hidden**; only the integer
    class is planner-visible (``docs/DECISIONS.md#d-006``).
    """

    kind: str = "uniform"
    base_multiplier: float = 1.0
    band_orientation: str = "vertical"  # barrier runs N-S ("vertical") or E-W
    band_position_frac: float = 0.62
    band_width_m: float = 150.0
    band_multiplier: float = 0.0
    patch_scale_m: float = 450.0
    patch_low: float = 0.45
    patch_high: float = 1.35
    n_classes: int = 4

    def __post_init__(self) -> None:
        _one_of(self.kind, ("uniform", "band", "patchy"), "fuels.kind")
        _non_negative(self.base_multiplier, "fuels.base_multiplier")
        _one_of(self.band_orientation, ("vertical", "horizontal"), "fuels.band_orientation")
        if not (0.0 < self.band_position_frac < 1.0):
            raise ConfigError("fuels.band_position_frac must lie in (0, 1)")
        _positive(self.band_width_m, "fuels.band_width_m")
        _non_negative(self.band_multiplier, "fuels.band_multiplier")
        _positive(self.patch_scale_m, "fuels.patch_scale_m")
        _non_negative(self.patch_low, "fuels.patch_low")
        if self.patch_high < self.patch_low:
            raise ConfigError("fuels.patch_high must be >= fuels.patch_low")
        if self.n_classes < 2:
            raise ConfigError("fuels.n_classes must be >= 2")


# --------------------------------------------------------------------------
# weather
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class WindWaypoint:
    """A waypoint of the piecewise-linear wind *target* schedule."""

    t_min: float = 0.0
    speed_ms: float = 0.0
    dir_deg: float = 0.0

    def __post_init__(self) -> None:
        _non_negative(self.t_min, "weather.schedule[].t_min")
        _non_negative(self.speed_ms, "weather.schedule[].speed_ms")


@dataclass(frozen=True)
class WeatherConfig:
    """Spatially uniform weather (``docs/ASSUMPTIONS.md#B-01``).

    ``schedule`` overrides ``wind_speed_ms``/``wind_dir_deg`` when non-empty; it
    is how a wind-shift scenario is expressed.  Fluctuation about the schedule
    is a mean-reverting AR(1) process.
    """

    wind_speed_ms: float = 0.0
    wind_dir_deg: float = 0.0
    schedule: list[WindWaypoint] = field(default_factory=list)
    speed_sigma_ms: float = 0.0
    dir_sigma_deg: float = 0.0
    speed_tau_min: float = 30.0
    dir_tau_min: float = 45.0
    temp_c: float = 18.0
    rh_pct: float = 35.0
    temp_sigma_c: float = 0.0
    rh_sigma_pct: float = 0.0
    temp_tau_min: float = 60.0
    rh_tau_min: float = 60.0
    step_min: float = 1.0

    _NESTED_LIST = {"schedule": WindWaypoint}

    def __post_init__(self) -> None:
        _non_negative(self.wind_speed_ms, "weather.wind_speed_ms")
        for name in (
            "speed_sigma_ms",
            "dir_sigma_deg",
            "temp_sigma_c",
            "rh_sigma_pct",
        ):
            _non_negative(getattr(self, name), f"weather.{name}")
        for name in ("speed_tau_min", "dir_tau_min", "temp_tau_min", "rh_tau_min", "step_min"):
            _positive(getattr(self, name), f"weather.{name}")
        times = [w.t_min for w in self.schedule]
        if times != sorted(times):
            raise ConfigError("weather.schedule must be ordered by t_min")


# --------------------------------------------------------------------------
# nature
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class IgnitionConfig:
    """An initial ignition, in local metres."""

    x_m: float = 0.0
    y_m: float = 0.0
    time_min: float = 0.0

    def __post_init__(self) -> None:
        _non_negative(self.time_min, "nature.ignitions[].time_min")


@dataclass(frozen=True)
class SpottingConfig:
    """Stochastic downwind spot ignition.  Disabled by default.

    When disabled the ``spotting_seed`` stream is not consumed at all, so
    ``enabled: false`` is exactly a model without spotting.
    """

    enabled: bool = False
    interval_min: float = 10.0
    rate_per_ha_per_min: float = 0.004
    median_distance_m: float = 420.0
    sigma_log: float = 0.55
    bearing_sigma_deg: float = 18.0
    p_ignite: float = 0.35
    max_spots_per_event: int = 25

    def __post_init__(self) -> None:
        _positive(self.interval_min, "nature.spotting.interval_min")
        _non_negative(self.rate_per_ha_per_min, "nature.spotting.rate_per_ha_per_min")
        _positive(self.median_distance_m, "nature.spotting.median_distance_m")
        _positive(self.sigma_log, "nature.spotting.sigma_log")
        _non_negative(self.bearing_sigma_deg, "nature.spotting.bearing_sigma_deg")
        _probability(self.p_ignite, "nature.spotting.p_ignite")
        if self.max_spots_per_event < 1:
            raise ConfigError("nature.spotting.max_spots_per_event must be >= 1")


@dataclass(frozen=True)
class NatureConfig:
    """Parameters of the synthetic nature model (``docs/NATURE_MODEL.md``).

    All coefficients are SYNTHETIC: chosen for controllability, not calibrated.
    """

    r0_base_m_per_min: float = 3.0
    spread_multiplier: float = 1.0
    residence_time_min: float = 30.0
    wind_coeff_a: float = 0.40
    wind_exp_b: float = 1.50
    slope_coeff_a: float = 3.00
    lb_coeff_c: float = 0.07
    lb_exp_p: float = 1.50
    stencil_max_offset: int = 2
    ignitions: list[IgnitionConfig] = field(default_factory=list)
    spotting: SpottingConfig = field(default_factory=SpottingConfig)

    _NESTED = {"spotting": SpottingConfig}
    _NESTED_LIST = {"ignitions": IgnitionConfig}

    def __post_init__(self) -> None:
        _positive(self.r0_base_m_per_min, "nature.r0_base_m_per_min")
        _positive(self.spread_multiplier, "nature.spread_multiplier")
        _positive(self.residence_time_min, "nature.residence_time_min")
        for name in ("wind_coeff_a", "wind_exp_b", "slope_coeff_a", "lb_coeff_c", "lb_exp_p"):
            _non_negative(getattr(self, name), f"nature.{name}")
        if self.stencil_max_offset not in (1, 2, 3):
            raise ConfigError(
                "nature.stencil_max_offset must be 1, 2 or 3 (8, 16 or 32 "
                f"propagation directions), got {self.stencil_max_offset!r}"
            )


# --------------------------------------------------------------------------
# observations
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LatencyConfig:
    """Latency budget.  Every component is non-negative by validation, which is
    what makes ``event <= acquisition <= processing <= availability`` structural
    (``docs/TIME_SEMANTICS.md#3``)."""

    acquisition_offset_min: float = 0.0
    processing_latency_min: float = 5.0
    delivery_latency_min: float = 2.0
    jitter_mean_min: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "acquisition_offset_min",
            "processing_latency_min",
            "delivery_latency_min",
            "jitter_mean_min",
        ):
            _non_negative(getattr(self, name), f"latency.{name}")

    @property
    def nominal_total_min(self) -> float:
        return (
            self.acquisition_offset_min
            + self.processing_latency_min
            + self.delivery_latency_min
        )


@dataclass(frozen=True)
class FireSensorConfig:
    """A GENERIC fire-detection sensor.

    Never named after or parameterised from a real instrument
    (``docs/DECISIONS.md#d-002``).
    """

    sensor_id: str = "fire_sensor_a"
    pixel_size_m: float = 375.0
    cadence_min: float = 30.0
    first_scan_offset_min: float = 5.0
    p_detect_max: float = 0.92
    detect_ref_area_m2: float = 20000.0
    geoloc_sigma_m: float = 150.0
    false_positive_rate_per_scan: float = 0.0
    latency: LatencyConfig = field(default_factory=LatencyConfig)

    _NESTED = {"latency": LatencyConfig}

    def __post_init__(self) -> None:
        _positive(self.pixel_size_m, "fire_sensor.pixel_size_m")
        _positive(self.cadence_min, "fire_sensor.cadence_min")
        _non_negative(self.first_scan_offset_min, "fire_sensor.first_scan_offset_min")
        _probability(self.p_detect_max, "fire_sensor.p_detect_max")
        _positive(self.detect_ref_area_m2, "fire_sensor.detect_ref_area_m2")
        _non_negative(self.geoloc_sigma_m, "fire_sensor.geoloc_sigma_m")
        _non_negative(
            self.false_positive_rate_per_scan, "fire_sensor.false_positive_rate_per_scan"
        )


@dataclass(frozen=True)
class StationLayoutConfig:
    """Where weather stations sit.  Positions are planner-visible."""

    kind: str = "grid"
    count: int = 9
    margin_frac: float = 0.12
    positions_m: list[list[float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        _one_of(self.kind, ("grid", "random", "explicit"), "weather_network.layout.kind")
        if self.kind == "explicit":
            if not self.positions_m:
                raise ConfigError("layout.kind='explicit' requires positions_m")
        elif self.count < 1:
            raise ConfigError("weather_network.layout.count must be >= 1")
        if not (0.0 <= self.margin_frac < 0.5):
            raise ConfigError("weather_network.layout.margin_frac must lie in [0, 0.5)")


@dataclass(frozen=True)
class WeatherNetworkConfig:
    """A GENERIC weather-station network."""

    network_id: str = "wx_net_a"
    layout: StationLayoutConfig = field(default_factory=StationLayoutConfig)
    cadence_min: float = 10.0
    first_obs_offset_min: float = 0.0
    sigma_speed_ms: float = 0.6
    sigma_dir_deg: float = 12.0
    sigma_temp_c: float = 0.5
    sigma_rh_pct: float = 3.0
    latency: LatencyConfig = field(
        default_factory=lambda: LatencyConfig(
            processing_latency_min=1.0, delivery_latency_min=1.0, jitter_mean_min=0.5
        )
    )

    _NESTED = {"layout": StationLayoutConfig, "latency": LatencyConfig}

    def __post_init__(self) -> None:
        _positive(self.cadence_min, "weather_network.cadence_min")
        _non_negative(self.first_obs_offset_min, "weather_network.first_obs_offset_min")
        for name in ("sigma_speed_ms", "sigma_dir_deg", "sigma_temp_c", "sigma_rh_pct"):
            _non_negative(getattr(self, name), f"weather_network.{name}")


@dataclass(frozen=True)
class MissingnessConfig:
    """Explicit missingness mode (``docs/OBSERVATION_MODEL.md#4``).

    ``fire_correlated`` is *informative* missingness: absence of data is
    correlated with the hidden fire.  Not leakage, but an exploitable channel
    (``docs/FAILURE_MODES.md#F-05``).
    """

    mode: str = "none"
    p_missing: float = 0.05
    p_fail: float = 0.02
    p_repair: float = 0.25
    tick_min: float = 10.0
    fail_radius_m: float = 400.0
    lambda_fire_per_min: float = 0.08
    down_duration_min: float = 1.0e9  # effectively permanent

    def __post_init__(self) -> None:
        _one_of(
            self.mode,
            ("none", "mcar", "correlated_outage", "fire_correlated"),
            "missingness.mode",
        )
        _probability(self.p_missing, "missingness.p_missing")
        _probability(self.p_fail, "missingness.p_fail")
        _probability(self.p_repair, "missingness.p_repair")
        _positive(self.tick_min, "missingness.tick_min")
        _positive(self.fail_radius_m, "missingness.fail_radius_m")
        _non_negative(self.lambda_fire_per_min, "missingness.lambda_fire_per_min")
        _positive(self.down_duration_min, "missingness.down_duration_min")


@dataclass(frozen=True)
class ObservationConfig:
    fire_sensors: list[FireSensorConfig] = field(
        default_factory=lambda: [FireSensorConfig()]
    )
    weather_network: WeatherNetworkConfig = field(default_factory=WeatherNetworkConfig)
    missingness: MissingnessConfig = field(default_factory=MissingnessConfig)

    _NESTED = {
        "weather_network": WeatherNetworkConfig,
        "missingness": MissingnessConfig,
    }
    _NESTED_LIST = {"fire_sensors": FireSensorConfig}

    def __post_init__(self) -> None:
        ids = [s.sensor_id for s in self.fire_sensors]
        if len(set(ids)) != len(ids):
            raise ConfigError(f"duplicate fire sensor ids: {ids}")


# --------------------------------------------------------------------------
# scenario
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioConfig:
    """A complete, self-contained description of one synthetic world."""

    name: str = "unnamed_scenario"
    description: str = ""
    epoch: str = "2026-04-01T09:00:00Z"
    master_seed: int = 20260919
    tags: list[str] = field(default_factory=list)
    grid: GridConfig = field(default_factory=GridConfig)
    time: TimeConfig = field(default_factory=TimeConfig)
    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    fuels: FuelsConfig = field(default_factory=FuelsConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    nature: NatureConfig = field(default_factory=NatureConfig)
    observations: ObservationConfig = field(default_factory=ObservationConfig)

    _NESTED = {
        "grid": GridConfig,
        "time": TimeConfig,
        "terrain": TerrainConfig,
        "fuels": FuelsConfig,
        "weather": WeatherConfig,
        "nature": NatureConfig,
        "observations": ObservationConfig,
    }

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ConfigError("scenario name must be non-empty")
        int(self.master_seed)  # raises TypeError -> surfaced by _build

    # -- construction ----------------------------------------------------
    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ScenarioConfig":
        cfg: ScenarioConfig = _build(cls, data, "scenario")
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ScenarioConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        return cls.from_mapping(raw)

    # -- cross-field validation -----------------------------------------
    def validate(self) -> None:
        """Cross-field checks that no single dataclass can make alone."""
        w, h = self.grid.width_m, self.grid.height_m
        if not self.nature.ignitions:
            raise ConfigError(
                "nature.ignitions must contain at least one ignition "
                "(an OSSE world with no fire is not useful; use "
                "nature.spread_multiplier to make it small instead)"
            )
        for k, ig in enumerate(self.nature.ignitions):
            if not (0.0 <= ig.x_m <= w and 0.0 <= ig.y_m <= h):
                raise ConfigError(
                    f"nature.ignitions[{k}] at ({ig.x_m}, {ig.y_m}) is outside the "
                    f"domain [0, {w}] x [0, {h}]"
                )
            if ig.time_min > self.time.horizon_min:
                raise ConfigError(
                    f"nature.ignitions[{k}].time_min exceeds time.horizon_min"
                )
        for wp in self.weather.schedule:
            if wp.t_min > self.time.horizon_min:
                raise ConfigError("weather.schedule extends beyond time.horizon_min")
        for pos in self.observations.weather_network.layout.positions_m:
            if len(pos) != 2:
                raise ConfigError("layout.positions_m entries must be [x_m, y_m]")
            if not (0.0 <= pos[0] <= w and 0.0 <= pos[1] <= h):
                raise ConfigError(f"station position {pos} is outside the domain")
        for s in self.observations.fire_sensors:
            if s.pixel_size_m < self.grid.cell_size_m:
                raise ConfigError(
                    f"fire sensor {s.sensor_id!r}: pixel_size_m "
                    f"({s.pixel_size_m}) is finer than the nature grid "
                    f"({self.grid.cell_size_m}); the observation process cannot "
                    "be finer than the truth it observes"
                )

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Plain-data form, suitable for JSON/YAML and for hashing."""
        return dataclasses.asdict(self)

    def config_hash(self) -> str:
        """Stable sha256 of the fully-defaulted configuration.

        Includes the master seed, so two worlds with the same hash are the same
        world.  Used to detect a silent config change between batches.
        """
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def replace(self, **overrides: Any) -> "ScenarioConfig":
        """Return a copy with top-level fields replaced (validated)."""
        merged = self.to_dict()
        merged.update(overrides)
        return ScenarioConfig.from_mapping(merged)


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Load and validate a scenario YAML file."""
    return ScenarioConfig.from_yaml(path)
