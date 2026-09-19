"""Batch summary statistics (``docs/VALIDATION.md#3``).

Reads ``batch_index.jsonl`` when present and falls back to each world's
``truth/world_summary.json``.  Both are experimenter-facing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation, ties averaged.  ``nan`` if degenerate."""
    if x.size < 3:
        return float("nan")
    rx, ry = _rank(x), _rank(y)
    sx, sy = rx.std(), ry.std()
    if sx == 0 or sy == 0:
        return float("nan")
    return float(np.mean((rx - rx.mean()) * (ry - ry.mean())) / (sx * sy))


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=float)
    ranks[order] = np.arange(values.size, dtype=float)
    # average ties so that a coarse sweep axis does not get an arbitrary order
    unique, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    for k, count in enumerate(counts):
        if count > 1:
            ranks[inverse == k] = ranks[inverse == k].mean()
    return ranks


def _stats(values: list[float]) -> dict[str, float | None]:
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return {"n": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "n": int(arr.size),
        "min": float(arr.min()),
        "median": float(np.median(arr)),
        "mean": float(arr.mean()),
        "max": float(arr.max()),
    }


def _collect(batch_dir: Path) -> list[dict[str, Any]]:
    index = batch_dir / "batch_index.jsonl"
    records: list[dict[str, Any]] = []
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    if records:
        return records
    for world in sorted(batch_dir.glob("world_*")):
        path = world / "truth/world_summary.json"
        if path.exists():
            records.append(
                {
                    "world_id": int(world.name.split("_")[-1]),
                    "path": world.name,
                    "summary": json.loads(path.read_text(encoding="utf-8")),
                }
            )
    return records


def summarize_batch(batch_dir: str | Path) -> dict[str, Any]:
    """Aggregate statistics over a generated batch."""
    batch_dir = Path(batch_dir)
    records = _collect(batch_dir)
    summaries = [r["summary"] for r in records]

    failures_path = batch_dir / "failures.jsonl"
    n_failures = (
        len([ln for ln in failures_path.read_text(encoding="utf-8").splitlines() if ln.strip()])
        if failures_path.exists()
        else 0
    )
    partials = sorted(p.name for p in batch_dir.glob(".world_*.partial"))

    def col(name: str) -> list[float]:
        return [s.get(name) for s in summaries]

    burned = np.asarray([s.get("burned_area_ha", np.nan) for s in summaries], dtype=float)
    wind = np.asarray(
        [s.get("sweep_axes", {}).get("wind_speed_ms", np.nan) for s in summaries], dtype=float
    )
    spread = np.asarray(
        [s.get("sweep_axes", {}).get("spread_multiplier", np.nan) for s in summaries],
        dtype=float,
    )
    ok = np.isfinite(burned)

    def rho(axis: np.ndarray) -> dict[str, Any]:
        sel = ok & np.isfinite(axis)
        return {"spearman_rho": _spearman(axis[sel], burned[sel]), "n": int(sel.sum())}

    flags: dict[str, int] = {}
    for record in records:
        world_dir = batch_dir / str(record.get("path", ""))
        meta = world_dir / "metadata/world_metadata.json"
        if meta.exists():
            for flag in json.loads(meta.read_text(encoding="utf-8")).get("flags", []):
                flags[flag] = flags.get(flag, 0) + 1

    return {
        "batch_dir": str(batch_dir),
        "n_worlds": len(records),
        "n_failures": n_failures,
        "n_partial_directories": len(partials),
        "partial_directories": partials,
        "flags": flags,
        "burned_area_ha": _stats(col("burned_area_ha")),
        "n_fire_detections": _stats(col("n_fire_detections")),
        "n_false_positive_detections": _stats(col("n_false_positive_detections")),
        "n_outage_scans": _stats(col("n_outage_scans")),
        "n_weather_obs": _stats(col("n_weather_obs")),
        "n_spot_ignitions": _stats(col("n_spot_ignitions")),
        "first_available_detection_min": _stats(col("first_available_detection_min")),
        "detection_latency_min": _stats(
            [
                (s.get("detection_latency_min") or {}).get("median")
                for s in summaries
            ]
        ),
        "monotonicity": {
            "burned_area_vs_wind_speed": rho(wind),
            "burned_area_vs_spread_multiplier": rho(spread),
            "note": (
                "Spearman rho over the batch. Both should be clearly positive; "
                "a near-zero value means the sweep axis is not doing what it "
                "claims, or the fire is saturating at the domain boundary "
                "(see flags.boundary_contact)."
            ),
        },
        "caveat": (
            "Statistics describe the synthetic system defined in "
            "docs/NATURE_MODEL.md and docs/OBSERVATION_MODEL.md. They are not "
            "statements about real wildfires (docs/SCOPE.md)."
        ),
    }


def summary_markdown(summary: dict[str, Any]) -> str:
    """Render a batch summary as a short Markdown report."""
    lines = [
        f"# OSSE batch summary — `{summary['batch_dir']}`",
        "",
        f"- worlds completed: **{summary['n_worlds']}**",
        f"- failures: **{summary['n_failures']}**",
        f"- partial (interrupted) directories: **{summary['n_partial_directories']}**",
        "",
        "## Flags",
    ]
    if summary["flags"]:
        lines += [f"- `{k}`: {v}" for k, v in sorted(summary["flags"].items())]
    else:
        lines.append("- none")

    lines += ["", "## Distributions", "", "| quantity | n | min | median | mean | max |", "|---|---|---|---|---|---|"]
    for key in (
        "burned_area_ha",
        "n_fire_detections",
        "n_false_positive_detections",
        "n_outage_scans",
        "n_weather_obs",
        "n_spot_ignitions",
        "first_available_detection_min",
        "detection_latency_min",
    ):
        s = summary[key]
        fmt = lambda v: "—" if v is None else f"{v:.3g}"  # noqa: E731
        lines.append(
            f"| `{key}` | {s['n']} | {fmt(s['min'])} | {fmt(s['median'])} | "
            f"{fmt(s['mean'])} | {fmt(s['max'])} |"
        )

    mono = summary["monotonicity"]
    lines += [
        "",
        "## Monotonicity checks",
        "",
        f"- burned area vs wind speed: ρ = {mono['burned_area_vs_wind_speed']['spearman_rho']:.3f} "
        f"(n = {mono['burned_area_vs_wind_speed']['n']})",
        f"- burned area vs spread multiplier: ρ = {mono['burned_area_vs_spread_multiplier']['spearman_rho']:.3f} "
        f"(n = {mono['burned_area_vs_spread_multiplier']['n']})",
        "",
        f"> {summary['caveat']}",
        "",
    ]
    return "\n".join(lines)
