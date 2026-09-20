"""Mode B: an independent, structurally different prediction model.

    D_s  -->  estimate front  -->  estimate motion  -->  project an ellipse

The nature model propagates a front by accumulating travel time across a
heterogeneous, slope- and fuel-dependent rate-of-spread raster under a
time-varying wind, with optional stochastic spot ignitions
(``docs/NATURE_MODEL.md``).  This planner does none of that.  It fits a single
growing ellipse to what the sensor has shown it and extrapolates.

The mismatch is the point.  Three **structural blind spots** are declared, not
injected:

1. **No terrain.**  Slope-driven anisotropy is invisible to it.
2. **No fuel heterogeneity beyond the published coarse class**, and the class
   is mapped to a rate factor by a rule that is not nature's rule.  A
   non-burnable barrier is therefore not predicted to stop anything.
3. **No spotting.**  A spot ignition ahead of the front cannot appear in the
   prediction at all.

Its rate law also differs in *form*: additive-linear in wind speed, where
nature is multiplicative in a power of wind speed.  Neither the form nor the
coefficients were fitted to nature, so the resulting error is genuine model
error rather than an error someone dialled in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .. import PLANNER_MODEL_VERSION
from ..degradation import DegradationSpec
from ..forecast import Forecast, empty_forecast
from ..info import InformationSet

#: Decision-grid cell size, metres.  Coarser than nature's 30 m on purpose: a
#: planner does not get truth resolution.
DECISION_CELL_SIZE_M = 120.0

#: Forecast lead time, minutes.  The valid window is ``[s, s + lead]``.
DEFAULT_LEAD_MIN = 90.0


@dataclass(frozen=True)
class PlannerCoefficients:
    """The planner's own spread law.  Not nature's, and not fitted to it.

    ``R_head = r0 + k_wind * U``            (m/min; nature is ``R0 (1 + a U^b)``)
    ``LB     = 1 + k_lb * U``               (nature is ``1 + c U^p``)

    Attributes:
        r0_m_per_min: no-wind head rate.
        k_wind_m_per_min_per_ms: linear wind response.
        k_lb_per_ms: length-to-breadth response to wind.
        obs_rate_weight: weight given to the rate measured from two
            consecutive scans, versus the wind law.
        rate_lo_m_per_min / rate_hi_m_per_min: plausibility bounds on the
            observed rate; outside them the wind law is used alone.
        fuel_class_low_factor: rate factor applied to the lowest visible fuel
            class, interpolated linearly to 1.0 at the highest class.
    """

    r0_m_per_min: float = 2.6
    k_wind_m_per_min_per_ms: float = 1.6
    k_lb_per_ms: float = 0.45
    obs_rate_weight: float = 0.6
    rate_lo_m_per_min: float = 0.2
    rate_hi_m_per_min: float = 60.0
    fuel_class_low_factor: float = 0.75


def _vector_mean_direction_rad(dirs_deg: np.ndarray) -> float:
    rad = np.radians(np.asarray(dirs_deg, dtype=float))
    return float(np.arctan2(np.mean(np.sin(rad)), np.mean(np.cos(rad))))


def _recent_wind(info: InformationSet, window_min: float = 30.0) -> tuple[float, float]:
    """Mean observed wind over the recent window: ``(speed_ms, dir_rad)``.

    Station observations only.  Each carries its own error and its own latency,
    so this is a noisy, late estimate of a spatially uniform truth -- exactly
    what the observation model says a planner may know.
    """
    wx = info.weather_observations
    times = wx.get("event_time_min")
    if times is None or len(times) == 0:
        return 0.0, 0.0
    t = times.astype(float)
    recent = t >= (float(np.max(t)) - window_min)
    speed = float(np.mean(wx["wind_speed_ms"].astype(float)[recent]))
    direction = _vector_mean_direction_rad(wx["wind_dir_deg"].astype(float)[recent])
    return max(0.0, speed), direction


def _scan_groups(info: InformationSet) -> list[tuple[float, np.ndarray]]:
    """Available detections grouped by scan, ordered by scan event time."""
    det = info.fire_detections
    if det.get("obs_id") is None or len(det["obs_id"]) == 0:
        return []
    times = det["event_time_min"].astype(float)
    xy = np.column_stack([det["x_m"].astype(float), det["y_m"].astype(float)])
    groups: list[tuple[float, np.ndarray]] = []
    for t in sorted(set(times.tolist())):
        groups.append((float(t), xy[times == t]))
    return groups


def _fuel_rate_factor(
    info: InformationSet, coeff: PlannerCoefficients, shape: tuple[int, int]
) -> np.ndarray:
    """Coarse rate factor from the published fuel class.

    Legitimate: ``observations/static_context/fuel_class.npy`` is
    planner-visible (``docs/DECISIONS.md#d-006``).  The *mapping* from class to
    rate is the planner's own guess and is not nature's continuous multiplier,
    which stays hidden.
    """
    fine = info.static_context.get("fuel_class")
    if fine is None:
        return np.ones(shape, dtype=float)
    fine = np.asarray(fine)
    hi = float(np.max(fine)) if fine.size else 0.0
    if hi <= 0:
        return np.ones(shape, dtype=float)
    ny, nx = shape
    yi = np.clip((np.arange(ny) * fine.shape[0] / ny).astype(int), 0, fine.shape[0] - 1)
    xi = np.clip((np.arange(nx) * fine.shape[1] / nx).astype(int), 0, fine.shape[1] - 1)
    coarse = fine[np.ix_(yi, xi)].astype(float)
    lo = coeff.fuel_class_low_factor
    return lo + (1.0 - lo) * (coarse / hi)


@dataclass(frozen=True)
class IndependentPlanner:
    """Produces an ``INDEPENDENT_MODEL_FORECAST`` from ``D_s`` alone."""

    coefficients: PlannerCoefficients = PlannerCoefficients()
    cell_size_m: float = DECISION_CELL_SIZE_M
    lead_min: float = DEFAULT_LEAD_MIN
    model_version: str = PLANNER_MODEL_VERSION

    def decision_grid_shape(self, info: InformationSet) -> tuple[int, int]:
        w = float(info.grid_meta["width_m"])
        h = float(info.grid_meta["height_m"])
        return (int(math.ceil(h / self.cell_size_m)),
                int(math.ceil(w / self.cell_size_m)))

    def forecast(
        self, info: InformationSet, degradation: DegradationSpec | None = None
    ) -> Forecast:
        """Issue a forecast valid over ``[s, s + lead]``.

        Args:
            info: the information set at ``s``.  The **only** input.
            degradation: optional stress-test perturbation applied to the
                planner's own estimate (direction bias, latency).  Declared as
                ``STRESS_TEST`` provenance, never presented as model error.

        Returns:
            A :class:`~wildfireguardian_fv.forecast.Forecast`.  A world with no
            usable evidence yields an explicit empty forecast, not ``None``:
            the policy must still act.
        """
        deg = degradation or DegradationSpec()
        s = float(info.information_time_min)
        availability = s + float(deg.latency_min)
        valid_to = min(s + self.lead_min, float(info.horizon_min))
        shape = self.decision_grid_shape(info)
        prov = ("INDEPENDENT_MODEL_FORECAST", f"planner:{self.model_version}")
        prov += deg.provenance()
        fid = f"w{info.world_id}-s{s:g}-{deg.label}-modeB"

        groups = _scan_groups(info)
        if not groups:
            return empty_forecast(
                fid, "INDEPENDENT_MODEL_FORECAST", "NO_FIRE_EVIDENCE", s,
                availability, valid_to, shape, self.cell_size_m, prov,
                {"reason": "no detection available at s"},
            )

        speed_ms, wind_dir_rad = _recent_wind(info)
        coeff = self.coefficients
        r_head_wind = coeff.r0_m_per_min + coeff.k_wind_m_per_min_per_ms * speed_ms

        t_first, p_first = groups[0]
        t_last, p_last = groups[-1]
        origin = p_first.mean(axis=0)

        # Heading: observed centroid motion if two distinct scans exist,
        # otherwise the observed wind.  Never truth.
        if len(groups) >= 2 and t_last > t_first:
            move = p_last.mean(axis=0) - origin
            heading = (
                float(math.atan2(move[1], move[0]))
                if float(np.hypot(*move)) > 1e-6
                else wind_dir_rad
            )
        else:
            heading = wind_dir_rad

        heading += math.radians(float(deg.direction_bias_deg))
        u = np.array([math.cos(heading), math.sin(heading)])

        # Head rate from the advance of the leading edge along the heading.
        r_head = r_head_wind
        rate_source = "wind_law"
        if len(groups) >= 2 and (t_last - t_first) > 0:
            head_first = float(np.max((p_first - origin) @ u))
            head_last = float(np.max((p_last - origin) @ u))
            r_obs = (head_last - head_first) / (t_last - t_first)
            if coeff.rate_lo_m_per_min <= r_obs <= coeff.rate_hi_m_per_min:
                w_obs = coeff.obs_rate_weight
                r_head = w_obs * r_obs + (1.0 - w_obs) * r_head_wind
                rate_source = "blended"
        r_head = max(r_head, coeff.rate_lo_m_per_min)

        # Ellipse shape from the planner's own length-to-breadth law.
        lb = 1.0 + coeff.k_lb_per_ms * speed_ms
        lb = max(lb, 1.0001)
        ecc = math.sqrt(max(lb * lb - 1.0, 0.0)) / lb

        # Origin time by back-extrapolation from the latest observed head.
        head_last_dist = float(np.max((p_last - origin) @ u))
        t_origin = t_last - max(head_last_dist, 0.0) / r_head

        ny, nx = shape
        xs = (np.arange(nx) + 0.5) * self.cell_size_m
        ys = (np.arange(ny) + 0.5) * self.cell_size_m
        gx, gy = np.meshgrid(xs, ys)
        dx, dy = gx - origin[0], gy - origin[1]
        dist = np.hypot(dx, dy)
        # Angle from the heading; the ellipse has a focus at the origin.
        cos_phi = np.clip((dx * u[0] + dy * u[1]) / np.maximum(dist, 1e-9), -1.0, 1.0)
        rate = r_head * (1.0 - ecc) / np.maximum(1.0 - ecc * cos_phi, 1e-6)
        rate = rate * _fuel_rate_factor(info, coeff, shape)

        predicted = t_origin + dist / np.maximum(rate, 1e-6)
        predicted = predicted * float(deg.rate_bias_factor)
        # Nothing can arrive before the planner believes the fire started, and
        # anything past the valid window is reported as "no arrival predicted".
        predicted = np.maximum(predicted, t_origin)
        predicted = np.where(predicted <= valid_to, predicted, np.inf)

        return Forecast(
            forecast_id=fid,
            mode="INDEPENDENT_MODEL_FORECAST",
            status="ISSUED",
            issue_time_min=s,
            availability_time_min=availability,
            valid_from_min=s,
            valid_to_min=valid_to,
            cell_size_m=self.cell_size_m,
            predicted_arrival_time_min=predicted,
            provenance=prov,
            diagnostics={
                "n_scans_used": len(groups),
                "n_detections_used": int(sum(len(g[1]) for g in groups)),
                "observed_wind_speed_ms": speed_ms,
                "heading_deg": math.degrees(heading) % 360.0,
                "r_head_m_per_min": r_head,
                "rate_source": rate_source,
                "length_to_breadth": lb,
                "estimated_origin_xy_m": [float(origin[0]), float(origin[1])],
                "estimated_origin_time_min": float(t_origin),
            },
        )
