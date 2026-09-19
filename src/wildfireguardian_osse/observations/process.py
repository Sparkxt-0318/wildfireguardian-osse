"""Assembly of the complete observation process for one world.

    HIDDEN NATURE WORLD  ->  OBSERVATION PROCESS  ->  AVAILABLE OBSERVATIONS

Everything planner-facing that a world contains is produced here, and nothing
else is.  Hidden by-products (which detections were spurious, when each sensor
was really down, the generative parameters) are kept separately and written
under ``truth/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import ScenarioConfig
from ..nature.world import NatureTruth
from ..rng import SeedRegistry
from ..sensors import (
    hidden_fire_sensor_params,
    hidden_weather_network_params,
    published_fire_sensor_spec,
    published_weather_network_spec,
)
from ..storage.tables import Table
from ..timeline import parse_epoch, to_utc
from .fire import generate_fire_observations
from .missingness import AvailabilityModel
from .weather import (
    build_stations,
    fire_exposure_times,
    generate_weather_observations,
)


@dataclass
class ObservationBundle:
    """Planner-facing tables plus the hidden by-products of the process."""

    # planner-visible
    fire_detections: Table
    fire_scan_log: Table
    weather_observations: Table
    station_metadata: list[dict]
    published_specs: dict[str, Any]
    # hidden truth
    detection_ledger: Table
    sensor_state: Table
    hidden_params: dict[str, Any] = field(default_factory=dict)

    def n_detections(self) -> int:
        return len(self.fire_detections)

    def first_available_detection_min(self) -> float:
        """Earliest time a detection could legally be used.  ``inf`` if never."""
        col = self.fire_detections.columns.get("availability_time_min")
        if col is None or len(col) == 0:
            return float("inf")
        return float(np.min(col.astype(float)))


def _add_utc(columns: dict[str, list], epoch) -> dict[str, list]:
    """Append presentational ISO-8601 columns next to the minute columns."""
    out = dict(columns)
    out["event_time_utc"] = [to_utc(epoch, t) for t in columns["event_time_min"]]
    out["availability_time_utc"] = [
        to_utc(epoch, t) for t in columns["availability_time_min"]
    ]
    return out


def run_observation_process(
    cfg: ScenarioConfig, truth: NatureTruth, seeds: SeedRegistry
) -> ObservationBundle:
    """Run every observation stream for one world.

    Args:
        cfg: the scenario configuration.
        truth: the hidden world.
        seeds: the world's derived random streams.  Only ``sensor_seed`` and
            ``missingness_seed`` are touched here, which is what makes the
            observation configuration unable to perturb the truth.

    Returns:
        An :class:`ObservationBundle`.
    """
    epoch = parse_epoch(cfg.epoch)
    net = cfg.observations.weather_network
    layout = build_stations(net.layout, truth.grid, net.network_id, seeds)

    exposure = fire_exposure_times(
        layout, truth, cfg.observations.missingness.fail_radius_m
    )
    # A fire sensor is not at a point in the domain, so it has no distance to
    # the fire; under fire_correlated missingness it is exposed as soon as
    # anything is burning.  Stated explicitly rather than left to a KeyError.
    first_ignition = float(np.min(truth.arrival_time_min))

    def exposure_time(entity_id: str) -> float:
        return exposure.get(entity_id, first_ignition)

    availability = AvailabilityModel(
        cfg=cfg.observations.missingness,
        seeds=seeds,
        horizon_min=cfg.time.horizon_min,
        fire_exposure_time=exposure_time,
    )

    fire = generate_fire_observations(cfg, truth, seeds, availability)
    weather = generate_weather_observations(cfg, truth, seeds, availability, layout)

    detections = Table.from_columns(_add_utc(fire.detections, epoch))
    if len(detections):
        detections = detections.sort_by("availability_time_min", "obs_id")
    scan_log = Table.from_columns(_add_utc(fire.scans, epoch))
    if len(scan_log):
        scan_log = scan_log.sort_by("availability_time_min", "scan_id")
    wx = Table.from_columns(_add_utc(weather.observations, epoch))
    if len(wx):
        wx = wx.sort_by("availability_time_min", "obs_id")

    ledger = Table.from_columns(fire.ledger)
    if len(ledger):
        ledger = ledger.sort_by("event_time_min", "obs_id")
    sensor_state = Table.from_columns(
        {
            "entity_id": [d.entity_id for d in availability.down_intervals],
            "start_min": [d.start_min for d in availability.down_intervals],
            "end_min": [d.end_min for d in availability.down_intervals],
            "cause": [d.cause for d in availability.down_intervals],
        }
    )
    if len(sensor_state):
        sensor_state = sensor_state.sort_by("start_min", "entity_id")

    published = {
        "note": (
            "Nominal, published specifications only. Generative error "
            "parameters are hidden truth (docs/OBSERVATION_MODEL.md#2.6)."
        ),
        "fire_sensors": [
            published_fire_sensor_spec(s) for s in cfg.observations.fire_sensors
        ],
        "weather_network": published_weather_network_spec(net),
    }
    hidden_params = {
        "fire_sensors": [
            hidden_fire_sensor_params(s) for s in cfg.observations.fire_sensors
        ],
        **hidden_weather_network_params(net, cfg.observations.missingness),
        "station_fire_exposure_min": exposure,
    }

    return ObservationBundle(
        fire_detections=detections,
        fire_scan_log=scan_log,
        weather_observations=wx,
        station_metadata=layout.as_records(),
        published_specs=published,
        detection_ledger=ledger,
        sensor_state=sensor_state,
        hidden_params=hidden_params,
    )
