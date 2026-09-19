"""Generic sensor specifications.

No sensor in this laboratory is named after, or parameterised from, a real
instrument (``docs/DECISIONS.md#d-002``).  This module also owns the block-list
used to enforce that.
"""

from .specs import (
    REAL_INSTRUMENT_NAMES,
    hidden_fire_sensor_params,
    hidden_weather_network_params,
    looks_like_real_instrument,
    published_fire_sensor_spec,
    published_weather_network_spec,
)

__all__ = [
    "REAL_INSTRUMENT_NAMES",
    "hidden_fire_sensor_params",
    "hidden_weather_network_params",
    "looks_like_real_instrument",
    "published_fire_sensor_spec",
    "published_weather_network_spec",
]
