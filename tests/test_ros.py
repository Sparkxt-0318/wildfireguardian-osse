"""Elliptical rate-of-spread identities (``docs/NATURE_MODEL.md#3``)."""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_osse.nature.ros import (
    RosCoefficients,
    build_ros_field,
    directional_ros,
    eccentricity,
    length_to_breadth,
)

COEFFS = RosCoefficients()


def _field(wind_ms: float, slope_factor: float = 0.0, upslope: float = 0.0):
    shape = (3, 3)
    return build_ros_field(
        r0=np.full(shape, 3.0),
        slope_factor=np.full(shape, slope_factor),
        upslope_dir_rad=np.full(shape, upslope),
        wind_speed_ms=wind_ms,
        wind_dir_rad=0.0,
        coeffs=COEFFS,
    )


def test_no_wind_no_slope_is_isotropic():
    field = _field(0.0)
    assert field.ecc[0, 0] == pytest.approx(0.0)
    rates = [field.in_direction(np.cos(a), np.sin(a))[0, 0] for a in np.linspace(0, 2 * np.pi, 16)]
    assert np.allclose(rates, 3.0)


def test_heading_backing_and_flank_identities():
    field = _field(6.0)
    e = float(field.ecc[0, 0])
    r_head = float(field.r_head[0, 0])
    assert e > 0.0
    assert field.in_direction(1.0, 0.0)[0, 0] == pytest.approx(r_head)
    assert field.in_direction(-1.0, 0.0)[0, 0] == pytest.approx(r_head * (1 - e) / (1 + e))
    assert field.in_direction(0.0, 1.0)[0, 0] == pytest.approx(r_head * (1 - e) / 1.0)


def test_rate_is_maximal_at_the_head_and_minimal_behind_it():
    field = _field(8.0)
    angles = np.linspace(0, 2 * np.pi, 361)
    rates = np.array([field.in_direction(np.cos(a), np.sin(a))[0, 0] for a in angles])
    assert angles[int(np.argmax(rates))] == pytest.approx(0.0, abs=0.02)
    assert angles[int(np.argmin(rates))] == pytest.approx(np.pi, abs=0.02)


def test_length_to_breadth_is_the_axis_ratio():
    phi = 4.0
    lb = float(length_to_breadth(phi, COEFFS.lb_coeff_c, COEFFS.lb_exp_p))
    e = float(eccentricity(lb))
    r_head = 10.0
    long_axis = r_head + r_head * (1 - e) / (1 + e)     # head + back
    short_axis = 2.0 * r_head * (1 - e) / np.sqrt(1 - e**2)  # 2 * semi-minor
    assert long_axis / short_axis == pytest.approx(lb, rel=1e-9)


def test_head_rate_and_eccentricity_increase_with_wind():
    heads = [float(_field(u).r_head[0, 0]) for u in (0.0, 2.0, 5.0, 9.0)]
    eccs = [float(_field(u).ecc[0, 0]) for u in (0.0, 2.0, 5.0, 9.0)]
    assert heads == sorted(heads) and heads[0] < heads[-1]
    assert eccs == sorted(eccs) and eccs[0] == pytest.approx(0.0)


def test_wind_and_slope_combine_as_vectors():
    """Wind east and slope north give a head direction in between."""
    field = build_ros_field(
        r0=np.full((1, 1), 3.0),
        slope_factor=np.full((1, 1), 1.0),
        upslope_dir_rad=np.full((1, 1), np.pi / 2),
        wind_speed_ms=3.0,
        wind_dir_rad=0.0,
        coeffs=COEFFS,
    )
    heading = float(np.arctan2(field.sin_head[0, 0], field.cos_head[0, 0]))
    assert 0.0 < heading < np.pi / 2
    phi_w = COEFFS.wind_factor(3.0)
    assert heading == pytest.approx(float(np.arctan2(1.0, phi_w)))


def test_directional_ros_matches_the_field_helper():
    field = _field(5.0)
    theta = 0.7
    expected = directional_ros(field.r_head[0, 0], field.ecc[0, 0], 0.0, theta)
    assert field.in_direction(np.cos(theta), np.sin(theta))[0, 0] == pytest.approx(expected)
