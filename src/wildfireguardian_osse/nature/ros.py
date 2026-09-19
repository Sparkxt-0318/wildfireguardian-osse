"""Elliptical, wind- and slope-dependent rate of spread.

All coefficients are SYNTHETIC (``docs/ASSUMPTIONS.md#C-02``): the functional
forms belong to a family commonly used in the wildfire-simulation literature,
but no value here is calibrated against any fire.

The model, per cell (``docs/NATURE_MODEL.md#3``)::

    phi_w  = a_w * U**b_w                                  (wind enhancement)
    phi_s  = a_s * tan(slope)**2                           (slope enhancement)
    v      = phi_w * u_wind + phi_s * u_upslope            (vector combination)
    phi    = |v| ;  theta_head = atan2(v)
    R_head = R0 * (1 + phi)
    LB     = 1 + c_lb * phi**p_lb
    e      = sqrt(LB**2 - 1) / LB
    R(t)   = R_head * (1 - e) / (1 - e * cos(t - theta_head))

At ``phi = 0`` this degenerates to ``LB = 1``, ``e = 0``, ``R = R0`` in every
direction -- the isotropic control case that validation world V1 checks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import NatureConfig


@dataclass(frozen=True)
class RosCoefficients:
    """Synthetic coefficients of the rate-of-spread model."""

    wind_coeff_a: float = 0.40
    wind_exp_b: float = 1.50
    slope_coeff_a: float = 3.00
    lb_coeff_c: float = 0.07
    lb_exp_p: float = 1.50

    @classmethod
    def from_config(cls, cfg: NatureConfig) -> "RosCoefficients":
        return cls(
            wind_coeff_a=float(cfg.wind_coeff_a),
            wind_exp_b=float(cfg.wind_exp_b),
            slope_coeff_a=float(cfg.slope_coeff_a),
            lb_coeff_c=float(cfg.lb_coeff_c),
            lb_exp_p=float(cfg.lb_exp_p),
        )

    def wind_factor(self, wind_speed_ms: float) -> float:
        """Dimensionless wind enhancement ``phi_w``."""
        u = max(0.0, float(wind_speed_ms))
        return float(self.wind_coeff_a * u**self.wind_exp_b)

    def slope_factor(self, slope_rad: np.ndarray) -> np.ndarray:
        """Dimensionless slope enhancement ``phi_s``, per cell."""
        return self.slope_coeff_a * np.tan(np.asarray(slope_rad, dtype=float)) ** 2


def length_to_breadth(phi: np.ndarray | float, coeff_c: float, exp_p: float):
    """Length-to-breadth ratio of the spread ellipse.  ``phi = 0`` gives 1."""
    return 1.0 + coeff_c * np.power(np.maximum(np.asarray(phi, dtype=float), 0.0), exp_p)


def eccentricity(lb: np.ndarray | float) -> np.ndarray:
    """Ellipse eccentricity from the length-to-breadth ratio."""
    lb_arr = np.maximum(np.asarray(lb, dtype=float), 1.0)
    return np.sqrt(np.maximum(lb_arr**2 - 1.0, 0.0)) / lb_arr


def directional_ros(
    r_head: np.ndarray | float,
    ecc: np.ndarray | float,
    theta_head: np.ndarray | float,
    theta: np.ndarray | float,
):
    """Spread rate in direction ``theta`` for a focus-at-ignition ellipse.

    Args:
        r_head: heading (maximum) rate of spread, m/min.
        ecc: ellipse eccentricity in ``[0, 1)``.
        theta_head: heading direction, radians CCW from east.
        theta: direction of interest, radians.

    Returns:
        Spread rate in direction ``theta``, m/min.

    Identities (tested in ``tests/test_ros.py``):
        ``theta = theta_head`` gives ``r_head``;
        ``theta = theta_head + pi`` gives ``r_head * (1-e)/(1+e)``;
        ``e = 0`` gives ``r_head`` for every ``theta``.
    """
    e = np.asarray(ecc, dtype=float)
    return np.asarray(r_head, dtype=float) * (1.0 - e) / (
        1.0 - e * np.cos(np.asarray(theta, dtype=float) - np.asarray(theta_head, dtype=float))
    )


@dataclass(frozen=True)
class RosField:
    """Per-cell rate-of-spread state at one instant.

    ``cos_head``/``sin_head`` are carried instead of the angle itself so that
    directional rates can be evaluated without a per-direction ``atan2``.
    """

    r_head: np.ndarray
    ecc: np.ndarray
    cos_head: np.ndarray
    sin_head: np.ndarray
    phi: np.ndarray

    def in_direction(self, cos_theta: float, sin_theta: float) -> np.ndarray:
        """Spread rate toward a fixed compass direction, per cell."""
        cos_delta = cos_theta * self.cos_head + sin_theta * self.sin_head
        return self.r_head * (1.0 - self.ecc) / (1.0 - self.ecc * cos_delta)


def build_ros_field(
    r0: np.ndarray,
    slope_factor: np.ndarray,
    upslope_dir_rad: np.ndarray,
    wind_speed_ms: float,
    wind_dir_rad: float,
    coeffs: RosCoefficients,
) -> RosField:
    """Assemble the per-cell elliptical rate-of-spread state.

    Args:
        r0: base rate of spread per cell, m/min (already includes fuel).
        slope_factor: ``phi_s`` per cell.
        upslope_dir_rad: direction of steepest ascent per cell.
        wind_speed_ms: uniform wind speed at this instant.
        wind_dir_rad: direction the wind blows **toward**, radians CCW from east.
        coeffs: synthetic model coefficients.

    Returns:
        A :class:`RosField`.
    """
    phi_w = coeffs.wind_factor(wind_speed_ms)
    vx = phi_w * np.cos(wind_dir_rad) + slope_factor * np.cos(upslope_dir_rad)
    vy = phi_w * np.sin(wind_dir_rad) + slope_factor * np.sin(upslope_dir_rad)
    phi = np.hypot(vx, vy)

    # Where phi == 0 the head direction is undefined; any direction gives the
    # same isotropic answer because e == 0, so east is chosen deterministically.
    norm = np.where(phi > 0.0, phi, 1.0)
    cos_head = np.where(phi > 0.0, vx / norm, 1.0)
    sin_head = np.where(phi > 0.0, vy / norm, 0.0)

    lb = length_to_breadth(phi, coeffs.lb_coeff_c, coeffs.lb_exp_p)
    return RosField(
        r_head=r0 * (1.0 + phi),
        ecc=eccentricity(lb),
        cos_head=cos_head,
        sin_head=sin_head,
        phi=phi,
    )
