"""Generic fire-detection observation stream (``docs/OBSERVATION_MODEL.md#2``).

At each scan the sensor sees the **actively burning set** at the (snapped) scan
time -- never the full burned area, never anything in the future.  Every
departure from truth is a named parameter: footprint, detection probability,
geolocation noise, false-alarm rate, latency, outage.

Random consumption per scan is a constant function of the configuration (every
pixel is drawn for, whether or not it is burning), so the fire state can never
shift the random stream.  That is what makes prefix causality hold for this
stream (``docs/TIME_SEMANTICS.md#6``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import FireSensorConfig, ScenarioConfig
from ..landscape.grid import Grid
from ..nature.world import NatureTruth
from ..rng import SeedRegistry
from ..timeline import build_time_arrays, snap_to_step
from .missingness import AvailabilityModel

#: Coarse ordinal reported with each detection.  Deliberately 3-level: it is a
#: degraded proxy for how much of the pixel is alight, not the probability.
CONFIDENCE_LEVELS = ("low", "nominal", "high")


@dataclass
class FireObservationResult:
    """Planner-facing detections and scan log, plus the hidden ledger."""

    detections: dict[str, list] = field(default_factory=dict)
    scans: dict[str, list] = field(default_factory=dict)
    ledger: dict[str, list] = field(default_factory=dict)


def _pixel_index_map(grid: Grid, pixel_size_m: float) -> tuple[np.ndarray, int, int]:
    """Map every nature cell to a sensor-pixel index."""
    n_px = int(np.ceil(grid.width_m / pixel_size_m))
    n_py = int(np.ceil(grid.height_m / pixel_size_m))
    xs = (np.arange(grid.nx) + 0.5) * grid.cell_size_m
    ys = (np.arange(grid.ny) + 0.5) * grid.cell_size_m
    px = np.clip((xs / pixel_size_m).astype(int), 0, n_px - 1)
    py = np.clip((ys / pixel_size_m).astype(int), 0, n_py - 1)
    index = py[:, None] * n_px + px[None, :]
    return index, n_px, n_py


def _confidence(score: np.ndarray, draw: np.ndarray) -> np.ndarray:
    """Sample a 3-level confidence ordinal from a burning-fraction score.

    ``score`` in ``[0, 1]`` is ``1 - exp(-area/ref)``.  High score makes
    ``high`` likely but never certain, which is what keeps the label a genuine
    observation rather than a readout of the hidden detection probability.
    """
    p_high = 0.15 + 0.60 * score
    p_low = 0.15 + 0.40 * (1.0 - score)
    out = np.full(score.shape, "nominal", dtype=object)
    out[draw < p_high] = "high"
    out[draw > 1.0 - p_low] = "low"
    return out


def generate_fire_observations(
    cfg: ScenarioConfig,
    truth: NatureTruth,
    seeds: SeedRegistry,
    availability: AvailabilityModel,
) -> FireObservationResult:
    """Generate every fire sensor's detections, scan log and hidden ledger."""
    grid = truth.grid
    horizon_min = float(cfg.time.horizon_min)
    residence = float(cfg.nature.residence_time_min)

    det: dict[str, list] = {
        k: []
        for k in (
            "obs_id", "sensor_id", "scan_id",
            "event_time_min", "acquisition_time_min",
            "processing_time_min", "availability_time_min",
            "x_m", "y_m", "pixel_size_m", "geoloc_sigma_m", "confidence",
        )
    }
    scans: dict[str, list] = {
        k: []
        for k in (
            "scan_id", "sensor_id",
            "event_time_min", "acquisition_time_min",
            "processing_time_min", "availability_time_min",
            "status", "n_detections",
        )
    }
    ledger: dict[str, list] = {
        k: []
        for k in (
            "obs_id", "sensor_id", "scan_id", "event_time_min",
            "kind", "true_x_m", "true_y_m", "reported_x_m", "reported_y_m",
            "pixel_active_area_m2", "detection_probability",
        )
    }

    for sensor in cfg.observations.fire_sensors:
        _one_sensor(
            sensor, cfg, truth, seeds, availability, grid, residence,
            horizon_min, det, scans, ledger,
        )

    return FireObservationResult(detections=det, scans=scans, ledger=ledger)


def _one_sensor(
    sensor: FireSensorConfig,
    cfg: ScenarioConfig,
    truth: NatureTruth,
    seeds: SeedRegistry,
    availability: AvailabilityModel,
    grid: Grid,
    residence: float,
    horizon_min: float,
    det: dict[str, list],
    scans: dict[str, list],
    ledger: dict[str, list],
) -> None:
    index, n_px, n_py = _pixel_index_map(grid, sensor.pixel_size_m)
    n_pixels = n_px * n_py
    flat_index = index.reshape(-1)
    pixel_cx = ((np.arange(n_pixels) % n_px) + 0.5) * sensor.pixel_size_m
    pixel_cy = ((np.arange(n_pixels) // n_px) + 0.5) * sensor.pixel_size_m

    scan_times = []
    t = float(sensor.first_scan_offset_min)
    while t <= horizon_min + 1e-9:
        scan_times.append(snap_to_step(t, cfg.time.dt_min, horizon_min))
        t += float(sensor.cadence_min)
    scan_times_arr = np.asarray(scan_times, dtype=float)

    down = availability.dropped(sensor.sensor_id, scan_times_arr)

    rng = seeds.generator("sensor_seed", f"fire:{sensor.sensor_id}")
    # Latency jitter gets its own sub-stream.  Drawing it from `rng` would make
    # the per-scan draws start at a stream position that depends on the number
    # of scans -- so extending the horizon would change the detections of
    # earlier scans, breaking prefix causality (docs/TIME_SEMANTICS.md#6).
    # Always drawn and then scaled, so a zero-jitter configuration consumes the
    # same randomness as any other.
    jitter_rng = seeds.generator("sensor_seed", f"fire:{sensor.sensor_id}:jitter")
    jitter = jitter_rng.exponential(1.0, size=scan_times_arr.size) * float(
        sensor.latency.jitter_mean_min
    )

    times = build_time_arrays(
        scan_times_arr,
        acquisition_offset_min=sensor.latency.acquisition_offset_min,
        processing_latency_min=sensor.latency.processing_latency_min,
        delivery_latency_min=sensor.latency.delivery_latency_min,
        jitter_min=jitter,
    )

    cell_area = grid.cell_area_m2
    for s, t_scan in enumerate(scan_times_arr):
        scan_id = f"{sensor.sensor_id}:s{s:05d}"
        # Draw first, unconditionally: consumption must not depend on the fire
        # or on whether the sensor happens to be down.
        u_detect = rng.random(n_pixels)
        u_conf = rng.random(n_pixels)
        noise = rng.standard_normal((n_pixels, 2))
        n_fp = int(rng.poisson(float(sensor.false_positive_rate_per_scan)))
        fp_pos = rng.random((max(n_fp, 0), 2))
        u_conf_fp = rng.random(max(n_fp, 0))

        if bool(down[s]):
            for key, value in (
                ("scan_id", scan_id), ("sensor_id", sensor.sensor_id),
                ("status", "outage"), ("n_detections", 0),
            ):
                scans[key].append(value)
            for key in (
                "event_time_min", "acquisition_time_min",
                "processing_time_min", "availability_time_min",
            ):
                scans[key].append(float(times[key][s]))
            continue

        active = truth.active_mask(float(t_scan), residence).reshape(-1)
        counts = np.bincount(flat_index[active], minlength=n_pixels)
        area = counts.astype(float) * cell_area
        score = 1.0 - np.exp(-area / float(sensor.detect_ref_area_m2))
        p_det = float(sensor.p_detect_max) * score
        detected = (u_detect < p_det) & (area > 0.0)

        conf = _confidence(score, u_conf)
        n_reported = 0
        for p in np.flatnonzero(detected):
            x = float(pixel_cx[p] + noise[p, 0] * sensor.geoloc_sigma_m)
            y = float(pixel_cy[p] + noise[p, 1] * sensor.geoloc_sigma_m)
            obs_id = f"{scan_id}:p{int(p):06d}"
            _append_detection(
                det, obs_id, sensor, scan_id, times, s, x, y, str(conf[p])
            )
            _append_ledger(
                ledger, obs_id, sensor, scan_id, float(t_scan), "true_detection",
                float(pixel_cx[p]), float(pixel_cy[p]), x, y, float(area[p]),
                float(p_det[p]),
            )
            n_reported += 1

        for f in range(n_fp):
            x = float(fp_pos[f, 0] * grid.width_m)
            y = float(fp_pos[f, 1] * grid.height_m)
            obs_id = f"{scan_id}:f{f:06d}"
            conf_fp = str(_confidence(np.zeros(1), u_conf_fp[f : f + 1])[0])
            _append_detection(det, obs_id, sensor, scan_id, times, s, x, y, conf_fp)
            _append_ledger(
                ledger, obs_id, sensor, scan_id, float(t_scan), "false_positive",
                float("nan"), float("nan"), x, y, 0.0, 0.0,
            )
            n_reported += 1

        for key, value in (
            ("scan_id", scan_id), ("sensor_id", sensor.sensor_id),
            ("status", "ok"), ("n_detections", n_reported),
        ):
            scans[key].append(value)
        for key in (
            "event_time_min", "acquisition_time_min",
            "processing_time_min", "availability_time_min",
        ):
            scans[key].append(float(times[key][s]))


def _append_detection(det, obs_id, sensor, scan_id, times, s, x, y, confidence) -> None:
    det["obs_id"].append(obs_id)
    det["sensor_id"].append(sensor.sensor_id)
    det["scan_id"].append(scan_id)
    for key in (
        "event_time_min", "acquisition_time_min",
        "processing_time_min", "availability_time_min",
    ):
        det[key].append(float(times[key][s]))
    det["x_m"].append(x)
    det["y_m"].append(y)
    det["pixel_size_m"].append(float(sensor.pixel_size_m))
    det["geoloc_sigma_m"].append(float(sensor.geoloc_sigma_m))
    det["confidence"].append(confidence)


def _append_ledger(
    ledger, obs_id, sensor, scan_id, t_scan, kind, tx, ty, rx, ry, area, p_det
) -> None:
    ledger["obs_id"].append(obs_id)
    ledger["sensor_id"].append(sensor.sensor_id)
    ledger["scan_id"].append(scan_id)
    ledger["event_time_min"].append(float(t_scan))
    ledger["kind"].append(kind)
    ledger["true_x_m"].append(tx)
    ledger["true_y_m"].append(ty)
    ledger["reported_x_m"].append(rx)
    ledger["reported_y_m"].append(ry)
    ledger["pixel_active_area_m2"].append(area)
    ledger["detection_probability"].append(p_det)
