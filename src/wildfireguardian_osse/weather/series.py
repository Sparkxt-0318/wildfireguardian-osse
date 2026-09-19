"""Spatially uniform weather time series.

Wind speed and direction follow a mean-reverting AR(1) process about a
piecewise-linear *target schedule* (``docs/NATURE_MODEL.md#6``).  The schedule
is how a "wind-direction shift" scenario is expressed; the AR(1) fluctuation is
what makes station observations non-trivial.

Temperature and relative humidity are generated but do **not** feed back into
the fire model in v1 (``docs/ASSUMPTIONS.md#B-03``).  They exist so that the
weather observation stream is non-degenerate.

Spatial uniformity is the single largest unrealism of the laboratory
(``docs/ASSUMPTIONS.md#B-01``, first item of ``tasks/ROADMAP.md``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import TimeConfig, WeatherConfig
from ..rng import SeedRegistry


def _wrap_pi(a: np.ndarray | float) -> np.ndarray | float:
    """Wrap an angle to ``(-pi, pi]``."""
    return (np.asarray(a) + np.pi) % (2.0 * np.pi) - np.pi


@dataclass(frozen=True)
class WeatherSeries:
    """Uniform weather sampled on a regular time grid.

    Attributes:
        t_min: sample times, minutes since ``t0``, shape ``(n,)``.
        wind_speed_ms: wind speed, m/s.
        wind_dir_rad: direction the wind blows **toward**, CCW from east.
        temp_c, rh_pct: temperature and relative humidity.
    """

    t_min: np.ndarray
    wind_speed_ms: np.ndarray
    wind_dir_rad: np.ndarray
    temp_c: np.ndarray
    rh_pct: np.ndarray

    def at(self, t_min: float) -> tuple[float, float, float, float]:
        """Linearly interpolated weather at time ``t_min`` (clamped at the ends)."""
        t = float(np.clip(t_min, self.t_min[0], self.t_min[-1]))
        speed = float(np.interp(t, self.t_min, self.wind_speed_ms))
        # interpolate direction through its unit vector to avoid wrap artefacts
        cx = float(np.interp(t, self.t_min, np.cos(self.wind_dir_rad)))
        cy = float(np.interp(t, self.t_min, np.sin(self.wind_dir_rad)))
        direction = float(np.arctan2(cy, cx))
        temp = float(np.interp(t, self.t_min, self.temp_c))
        rh = float(np.interp(t, self.t_min, self.rh_pct))
        return speed, direction, temp, rh

    def sample_arrays(self, t_min: np.ndarray) -> dict[str, np.ndarray]:
        """Vectorised sampling at arbitrary times."""
        t = np.clip(np.asarray(t_min, dtype=float), self.t_min[0], self.t_min[-1])
        cx = np.interp(t, self.t_min, np.cos(self.wind_dir_rad))
        cy = np.interp(t, self.t_min, np.sin(self.wind_dir_rad))
        return {
            "wind_speed_ms": np.interp(t, self.t_min, self.wind_speed_ms),
            "wind_dir_rad": np.arctan2(cy, cx),
            "temp_c": np.interp(t, self.t_min, self.temp_c),
            "rh_pct": np.interp(t, self.t_min, self.rh_pct),
        }


def _schedule_targets(
    cfg: WeatherConfig, t_min: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Piecewise-linear target speed and direction from the wind schedule."""
    if not cfg.schedule:
        speed = np.full_like(t_min, float(cfg.wind_speed_ms))
        direction = np.full_like(t_min, np.deg2rad(cfg.wind_dir_deg))
        return speed, direction

    knots = np.array([w.t_min for w in cfg.schedule], dtype=float)
    speeds = np.array([w.speed_ms for w in cfg.schedule], dtype=float)
    dirs = np.deg2rad(np.array([w.dir_deg for w in cfg.schedule], dtype=float))

    target_speed = np.interp(t_min, knots, speeds)
    # Unwrap the knot directions so that a scheduled 90-degree shift rotates the
    # short way and never spins through the long arc.
    unwrapped = np.unwrap(dirs) if dirs.size > 1 else dirs
    target_dir = np.interp(t_min, knots, unwrapped)
    return target_speed, target_dir


def _ar1(
    target: np.ndarray,
    sigma: float,
    tau_min: float,
    step_min: float,
    rng: np.random.Generator,
    *,
    angular: bool = False,
) -> np.ndarray:
    """Mean-reverting AR(1) fluctuation about ``target``.

    ``rho = exp(-step/tau)``; the innovation is scaled by ``sqrt(1-rho^2)`` so
    that the stationary standard deviation of the deviation is ``sigma``
    regardless of ``step`` or ``tau``.
    """
    n = target.size
    out = np.empty(n, dtype=float)
    if sigma <= 0.0:
        return target.copy()
    rho = float(np.exp(-float(step_min) / float(tau_min)))
    innovation = sigma * np.sqrt(max(0.0, 1.0 - rho**2))
    dev = 0.0
    noise = rng.standard_normal(n)
    for k in range(n):
        dev = rho * dev + innovation * noise[k]
        out[k] = target[k] + dev
    if angular:
        return out
    return out


def build_weather(
    cfg: WeatherConfig, time_cfg: TimeConfig, seeds: "SeedRegistry"
) -> WeatherSeries:
    """Generate the hidden true weather series.

    Args:
        cfg: weather configuration.
        time_cfg: simulation time window.
        seeds: the world's seed registry.  Each variable draws from its own
            ``weather_seed`` sub-stream, so the number of samples taken for one
            variable can never shift another -- which is what keeps a longer
            horizon from changing the *earlier* part of the series
            (``docs/TIME_SEMANTICS.md#6``).

    Returns:
        A :class:`WeatherSeries` covering ``[0, horizon_min]`` inclusive.

    Note:
        The series is generated on ``weather.step_min``, independent of the
        simulation ``dt``, so that changing ``dt`` does not change the weather.
    """
    step = float(cfg.step_min)
    n = int(np.floor(time_cfg.horizon_min / step)) + 1
    t = np.arange(n, dtype=float) * step
    if t[-1] < time_cfg.horizon_min:  # always cover the horizon
        t = np.append(t, float(time_cfg.horizon_min))

    target_speed, target_dir = _schedule_targets(cfg, t)

    gen = lambda tag: seeds.generator("weather_seed", tag)  # noqa: E731

    speed = _ar1(target_speed, cfg.speed_sigma_ms, cfg.speed_tau_min, step, gen("speed"))
    speed = np.maximum(speed, 0.0)
    direction = _ar1(
        target_dir,
        np.deg2rad(cfg.dir_sigma_deg),
        cfg.dir_tau_min,
        step,
        gen("direction"),
        angular=True,
    )
    temp = _ar1(
        np.full_like(t, float(cfg.temp_c)), cfg.temp_sigma_c, cfg.temp_tau_min, step, gen("temp")
    )
    rh = np.clip(
        _ar1(
            np.full_like(t, float(cfg.rh_pct)),
            cfg.rh_sigma_pct,
            cfg.rh_tau_min,
            step,
            gen("rh"),
        ),
        0.0,
        100.0,
    )

    return WeatherSeries(
        t_min=t,
        wind_speed_ms=speed,
        wind_dir_rad=direction,
        temp_c=temp,
        rh_pct=rh,
    )
