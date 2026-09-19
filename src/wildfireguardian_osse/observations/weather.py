"""Generic weather-station observation stream (``docs/OBSERVATION_MODEL.md#3``).

Stations sample the hidden uniform weather at their cadence, add independent
Gaussian measurement error, and deliver after a latency.  Because wind is
spatially uniform in v1 (``docs/ASSUMPTIONS.md#B-01``), stations differ only
through their noise, cadence phase and missingness -- not through position.
That is a real limitation, not an oversight: spatial data assimilation cannot
be studied with these worlds (first item of ``tasks/ROADMAP.md``).

Station *positions* are planner-visible: a network's geometry is legitimately
known.  Station *errors* are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import ScenarioConfig, StationLayoutConfig
from ..landscape.grid import Grid
from ..nature.world import NatureTruth
from ..rng import SeedRegistry
from ..timeline import build_time_arrays, snap_to_step
from .missingness import AvailabilityModel


@dataclass(frozen=True)
class StationLayout:
    """Station identifiers and positions.  Planner-visible."""

    station_ids: list[str]
    x_m: np.ndarray
    y_m: np.ndarray

    def as_records(self) -> list[dict]:
        return [
            {"station_id": sid, "x_m": float(x), "y_m": float(y)}
            for sid, x, y in zip(self.station_ids, self.x_m, self.y_m)
        ]


def build_stations(
    cfg: StationLayoutConfig, grid: Grid, network_id: str, seeds: SeedRegistry
) -> StationLayout:
    """Place stations in the domain.

    Args:
        cfg: layout configuration (``grid``, ``random`` or ``explicit``).
        grid: raster geometry.
        network_id: used to build the id strings and the layout sub-stream.
        seeds: the world's seed registry (``sensor_seed`` sub-stream
            ``layout:<network_id>``; consumed only by ``kind='random'``).
    """
    if cfg.kind == "explicit":
        xs = np.array([p[0] for p in cfg.positions_m], dtype=float)
        ys = np.array([p[1] for p in cfg.positions_m], dtype=float)
    elif cfg.kind == "grid":
        side = int(np.ceil(np.sqrt(cfg.count)))
        frac = (np.arange(side) + 0.5) / side
        lo, hi = cfg.margin_frac, 1.0 - cfg.margin_frac
        frac = lo + frac * (hi - lo)
        gx, gy = np.meshgrid(frac * grid.width_m, frac * grid.height_m)
        xs = gx.reshape(-1)[: cfg.count]
        ys = gy.reshape(-1)[: cfg.count]
    elif cfg.kind == "random":
        rng = seeds.generator("sensor_seed", f"layout:{network_id}")
        lo, hi = cfg.margin_frac, 1.0 - cfg.margin_frac
        u = rng.random((cfg.count, 2)) * (hi - lo) + lo
        xs = u[:, 0] * grid.width_m
        ys = u[:, 1] * grid.height_m
    else:  # pragma: no cover - guarded by config validation
        raise ValueError(f"unhandled station layout {cfg.kind!r}")

    ids = [f"{network_id}:st{k:03d}" for k in range(len(xs))]
    return StationLayout(station_ids=ids, x_m=xs, y_m=ys)


@dataclass
class WeatherObservationResult:
    observations: dict[str, list] = field(default_factory=dict)
    layout: StationLayout | None = None


def fire_exposure_times(
    layout: StationLayout, truth: NatureTruth, radius_m: float
) -> dict[str, float]:
    """First minute at which the fire came within ``radius_m`` of each station.

    Hidden truth, used only to drive ``fire_correlated`` missingness.  It is
    never written to a planner-facing file.
    """
    X, Y = truth.grid.cell_centres()
    out: dict[str, float] = {}
    for sid, sx, sy in zip(layout.station_ids, layout.x_m, layout.y_m):
        near = np.hypot(X - sx, Y - sy) <= float(radius_m)
        times = truth.arrival_time_min[near]
        finite = times[np.isfinite(times)]
        out[sid] = float(finite.min()) if finite.size else float("inf")
    return out


def generate_weather_observations(
    cfg: ScenarioConfig,
    truth: NatureTruth,
    seeds: SeedRegistry,
    availability: AvailabilityModel,
    layout: StationLayout,
) -> WeatherObservationResult:
    """Generate the planner-facing weather-station records."""
    net = cfg.observations.weather_network
    horizon = float(cfg.time.horizon_min)

    times_list: list[float] = []
    t = float(net.first_obs_offset_min)
    while t <= horizon + 1e-9:
        times_list.append(snap_to_step(t, cfg.time.dt_min, horizon))
        t += float(net.cadence_min)
    obs_times = np.asarray(times_list, dtype=float)

    sampled = truth.weather.sample_arrays(obs_times)

    columns: dict[str, list] = {
        k: []
        for k in (
            "obs_id", "station_id",
            "event_time_min", "acquisition_time_min",
            "processing_time_min", "availability_time_min",
            "wind_speed_ms", "wind_dir_deg", "temp_c", "rh_pct",
            "sigma_speed_ms", "sigma_dir_deg",
        )
    }

    for k, sid in enumerate(layout.station_ids):
        rng = seeds.generator("sensor_seed", f"wx:{sid}")
        n = obs_times.size
        err = rng.standard_normal((n, 4))
        # Own sub-stream, for the same reason as the fire sensor's jitter: a
        # longer horizon must not shift the randomness of earlier records.
        jitter_rng = seeds.generator("sensor_seed", f"wx:{sid}:jitter")
        jitter = jitter_rng.exponential(1.0, size=n) * float(net.latency.jitter_mean_min)
        stamps = build_time_arrays(
            obs_times,
            acquisition_offset_min=net.latency.acquisition_offset_min,
            processing_latency_min=net.latency.processing_latency_min,
            delivery_latency_min=net.latency.delivery_latency_min,
            jitter_min=jitter,
        )
        dropped = availability.dropped(sid, obs_times)

        speed = np.maximum(sampled["wind_speed_ms"] + err[:, 0] * net.sigma_speed_ms, 0.0)
        direction = np.rad2deg(
            sampled["wind_dir_rad"] + np.deg2rad(net.sigma_dir_deg) * err[:, 1]
        ) % 360.0
        temp = sampled["temp_c"] + err[:, 2] * net.sigma_temp_c
        rh = np.clip(sampled["rh_pct"] + err[:, 3] * net.sigma_rh_pct, 0.0, 100.0)

        for m in range(n):
            if dropped[m]:
                continue
            columns["obs_id"].append(f"{sid}:o{m:05d}")
            columns["station_id"].append(sid)
            for key in (
                "event_time_min", "acquisition_time_min",
                "processing_time_min", "availability_time_min",
            ):
                columns[key].append(float(stamps[key][m]))
            columns["wind_speed_ms"].append(float(speed[m]))
            columns["wind_dir_deg"].append(float(direction[m]))
            columns["temp_c"].append(float(temp[m]))
            columns["rh_pct"].append(float(rh[m]))
            columns["sigma_speed_ms"].append(float(net.sigma_speed_ms))
            columns["sigma_dir_deg"].append(float(net.sigma_dir_deg))

    return WeatherObservationResult(observations=columns, layout=layout)
