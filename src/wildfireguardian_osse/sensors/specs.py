"""Published vs hidden sensor specifications.

A real observing product ships a *published* specification: its footprint, its
nominal revisit, its stated geolocation accuracy.  It does **not** ship the
generative parameters of its own error process.  This module makes that split
explicit so that it cannot be blurred by accident:

* :func:`published_fire_sensor_spec` -> planner-visible
  (``observations/sensor_specs_published.json``)
* :func:`hidden_fire_sensor_params` -> hidden truth
  (``truth/observation_params.json``)

If a parameter is not in the published dict, a planner must not see it.
"""

from __future__ import annotations

import dataclasses
import re

from ..config import FireSensorConfig, MissingnessConfig, WeatherNetworkConfig

#: Names of real instruments/platforms.  A sensor id or label matching any of
#: these is rejected: a generic sensor must never quietly acquire a real
#: instrument's authority (``docs/DECISIONS.md#d-002``).  This list is
#: deliberately broad; it is a tripwire, not a taxonomy.
REAL_INSTRUMENT_NAMES: tuple[str, ...] = (
    "viirs", "modis", "goes", "abi", "ahi", "gk2a", "gk-2a", "geo-kompsat",
    "himawari", "sentinel", "landsat", "avhrr", "seviri", "msg", "noaa-20",
    "suomi", "npp", "terra", "aqua", "firms", "insat", "fengyun", "meteosat",
    "kompsat", "planetscope", "worldview", "ecostress", "slstr", "olci",
)

_WORD = re.compile(r"[a-z0-9]+")


def looks_like_real_instrument(text: str) -> str | None:
    """Return the offending name if ``text`` names a real instrument.

    Matching is on whole alphanumeric tokens, so ``fire_sensor_a`` is fine and
    ``goes_like_sensor`` is not.  Hyphenated names such as ``gk-2a`` are also
    caught, because the de-punctuated form of the whole string is compared too.

    A free substring search was deliberately *not* used: it rejects innocent
    words (``cabin`` contains ``abi``), and a tripwire that cries wolf gets
    switched off.
    """
    lowered = str(text).lower()
    tokens = set(_WORD.findall(lowered))
    joined = "".join(_WORD.findall(lowered))
    for name in REAL_INSTRUMENT_NAMES:
        key = "".join(_WORD.findall(name))
        if key in tokens or key == joined:
            return name
    return None


def published_fire_sensor_spec(cfg: FireSensorConfig) -> dict:
    """Planner-visible nominal specification of a fire sensor.

    Deliberately excludes ``p_detect_max``, ``detect_ref_area_m2`` and
    ``false_positive_rate_per_scan``: those are the generative parameters of the
    error process and are hidden truth.
    """
    return {
        "sensor_id": cfg.sensor_id,
        "sensor_kind": "generic_fire_detection",
        "pixel_size_m": float(cfg.pixel_size_m),
        "nominal_cadence_min": float(cfg.cadence_min),
        "nominal_geoloc_sigma_m": float(cfg.geoloc_sigma_m),
        "nominal_latency_min": float(cfg.latency.nominal_total_min),
        "note": (
            "Generic synthetic sensor. Not modelled on any real instrument; "
            "detection probability and false-alarm parameters are not published."
        ),
    }


def published_weather_network_spec(cfg: WeatherNetworkConfig) -> dict:
    """Planner-visible nominal specification of a weather-station network."""
    return {
        "network_id": cfg.network_id,
        "sensor_kind": "generic_weather_station_network",
        "nominal_cadence_min": float(cfg.cadence_min),
        "nominal_sigma_speed_ms": float(cfg.sigma_speed_ms),
        "nominal_sigma_dir_deg": float(cfg.sigma_dir_deg),
        "nominal_latency_min": float(cfg.latency.nominal_total_min),
        "note": "Generic synthetic stations. Not modelled on any real network.",
    }


def hidden_fire_sensor_params(cfg: FireSensorConfig) -> dict:
    """Complete generative parameters of a fire sensor.  Hidden truth."""
    return dataclasses.asdict(cfg)


def hidden_weather_network_params(
    cfg: WeatherNetworkConfig, missingness: MissingnessConfig
) -> dict:
    """Complete generative parameters of the weather network.  Hidden truth."""
    return {
        "weather_network": dataclasses.asdict(cfg),
        "missingness": dataclasses.asdict(missingness),
    }
