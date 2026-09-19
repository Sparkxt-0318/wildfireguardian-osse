"""The observation process: hidden truth -> degraded, delayed, incomplete records.

The only channel from ``truth/`` to ``observations/``
(``docs/OBSERVATION_MODEL.md``).
"""

from .missingness import AvailabilityModel, DownInterval
from .fire import FireObservationResult, generate_fire_observations
from .weather import (
    StationLayout,
    WeatherObservationResult,
    build_stations,
    generate_weather_observations,
)
from .process import ObservationBundle, run_observation_process

__all__ = [
    "AvailabilityModel",
    "DownInterval",
    "FireObservationResult",
    "generate_fire_observations",
    "StationLayout",
    "WeatherObservationResult",
    "build_stations",
    "generate_weather_observations",
    "ObservationBundle",
    "run_observation_process",
]
