"""World-level validation: structure, checksums, timing, leakage, causality.

``wg-osse validate <world>`` is exactly :func:`validate_world`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..storage.manifest import verify_manifest
from ..storage.tables import read_table
from ..timeline import TIME_COLUMNS
from .leakage import scan_world_for_leakage

#: Planner-facing observation tables and whether they must carry the four times.
OBSERVATION_TABLES: tuple[str, ...] = (
    "observations/fire_detections.csv",
    "observations/fire_scan_log.csv",
    "observations/weather_station_obs.csv",
)

#: Files every completed world must contain.
REQUIRED_FILES: tuple[str, ...] = (
    "manifest.json",
    "metadata/world_metadata.json",
    "observations/fire_detections.csv",
    "observations/fire_scan_log.csv",
    "observations/weather_station_obs.csv",
    "observations/station_metadata.json",
    "observations/sensor_specs_published.json",
    "truth/arrival_time_min.npy",
    "truth/nature_params.json",
    "truth/world_summary.json",
)


def check_time_semantics(table: dict[str, np.ndarray], label: str) -> list[str]:
    """Check the four-time invariant on one observation table.

    Returns:
        Problems found; empty if ``event <= acquisition <= processing <=
        availability`` holds for every record (``docs/TIME_SEMANTICS.md``).
    """
    problems: list[str] = []
    missing = [c for c in TIME_COLUMNS if c not in table]
    if missing:
        return [f"{label}: missing time column(s) {missing}"]

    n = len(table[TIME_COLUMNS[0]])
    if n == 0:
        return problems

    columns = []
    for name in TIME_COLUMNS:
        try:
            columns.append(np.asarray(table[name], dtype=float))
        except (TypeError, ValueError):
            problems.append(
                f"{label}: column {name!r} is not numeric; the file is "
                "malformed and its times cannot be checked"
            )
    if len(columns) != len(TIME_COLUMNS):
        return problems
    for a, b in zip(columns, columns[1:]):
        bad = np.flatnonzero(a > b + 1e-9)
        if bad.size:
            k = int(bad[0])
            problems.append(
                f"{label}: observation time ordering violated at row {k} "
                f"({a[k]} > {b[k]}); see docs/TIME_SEMANTICS.md"
            )
    if np.any(~np.isfinite(np.concatenate(columns))):
        problems.append(f"{label}: non-finite observation time")
    return problems


def check_causal_sampling(world_dir: Path) -> list[str]:
    """Every true detection must correspond to fire that existed by its event time.

    Uses hidden truth, so it is an experimenter-side check, not something a
    planner could run.  It catches a whole class of future-leakage bugs that a
    field-name scan cannot: a detection generated from the fire's *later* state
    would show a pixel with no active area at the reported time.
    """
    ledger_path = world_dir / "truth/detection_ledger.csv"
    if not ledger_path.exists():
        return []
    ledger = read_table(ledger_path)
    if not ledger or len(next(iter(ledger.values()), [])) == 0:
        return []

    kinds = ledger.get("kind")
    if kinds is None:
        return ["truth/detection_ledger.csv: missing 'kind' column"]
    area = np.asarray(ledger["pixel_active_area_m2"], dtype=float)
    real = np.asarray([str(k) == "true_detection" for k in kinds])
    bad = real & ~(area > 0.0)
    if np.any(bad):
        return [
            f"truth/detection_ledger.csv: {int(np.count_nonzero(bad))} real "
            "detection(s) report a pixel with no actively burning area at the "
            "event time -- the sensor sampled a state that did not exist then"
        ]
    return []


def check_horizon(world_dir: Path) -> list[str]:
    """No observation may describe a state beyond the simulated horizon."""
    metadata = json.loads(
        (world_dir / "metadata/world_metadata.json").read_text(encoding="utf-8")
    )
    horizon = float(metadata["horizon_min"])
    problems: list[str] = []
    for rel in OBSERVATION_TABLES:
        table = read_table(world_dir / rel)
        col = table.get("event_time_min")
        if col is None or len(col) == 0:
            continue
        try:
            values = np.asarray(col, dtype=float)
        except (TypeError, ValueError):
            problems.append(f"{rel}: event_time_min is not numeric")
            continue
        if np.any(values > horizon + 1e-9):
            problems.append(
                f"{rel}: {int(np.count_nonzero(values > horizon + 1e-9))} record(s) "
                f"have event_time_min beyond the horizon {horizon}"
            )
        if np.any(values < -1e-9):
            problems.append(f"{rel}: negative event_time_min")
    return problems


def _safe_read(path: Path, problems: list[str]) -> dict[str, np.ndarray]:
    """Read a table, turning any parse failure into a reported problem."""
    try:
        return read_table(path)
    except Exception as exc:  # noqa: BLE001 - a corrupt world must not crash validate
        problems.append(f"{path.name}: could not be read ({type(exc).__name__}: {exc})")
        return {}


def validate_world(world_dir: str | Path) -> list[str]:
    """Full validation of a generated world.

    Returns:
        A list of problems.  Empty means the world passed every check:
        structure, manifest checksums, visibility labels, leakage scan, time
        semantics, causal sampling and horizon bounds.
    """
    world_dir = Path(world_dir)
    if not world_dir.is_dir():
        return [f"{world_dir}: not a directory"]

    problems: list[str] = []
    for required in REQUIRED_FILES:
        if not (world_dir / required).exists():
            problems.append(f"missing required file: {required}")
    if problems:
        return problems

    problems += verify_manifest(world_dir)
    problems += scan_world_for_leakage(world_dir)
    for rel in OBSERVATION_TABLES:
        table = _safe_read(world_dir / rel, problems)
        if table:
            problems += check_time_semantics(table, rel)
    problems += check_causal_sampling(world_dir)
    problems += check_horizon(world_dir)
    return problems
