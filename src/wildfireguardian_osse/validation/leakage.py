"""Leakage scanning: the executable form of ``docs/OBSERVATION_MODEL.md#6``.

Four independent attacks are run against every world, so that a single mistake
in one layer does not go unnoticed:

1. **Forbidden names** -- no planner-visible file may contain a field name (CSV
   header, JSON key) drawn from the hidden-parameter vocabulary.
2. **Forbidden values** -- no planner-visible file may contain a seed, and no
   planner-visible raster may reproduce a hidden raster (arrival times, burned
   mask, continuous fuel multiplier).  Only the two allow-listed static-context
   rasters may match their truth counterparts, and they must match exactly.
3. **Identifier leakage** -- no swept hidden value may appear in the scenario
   name, description or tags (``docs/DECISIONS.md#d-013``).
4. **Realism creep** -- no planner-visible text may name a real instrument
   (``docs/DECISIONS.md#d-002``).

A finding is returned as a human-readable string.  An empty list means the world
passed; it does **not** mean leakage is impossible, only that these four attacks
found none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..sensors.specs import looks_like_real_instrument
from ..storage.manifest import (
    PLANNER_VISIBLE,
    STATIC_CONTEXT_ALLOWLIST,
)
from ..storage.tables import read_table

#: Substrings that must not appear in any planner-visible field name.  These
#: are the names of hidden nature parameters, hidden observation parameters and
#: truth quantities.  Matching is case-insensitive substring matching on field
#: names only -- never on free text, which would fire on documentation.
FORBIDDEN_KEY_FRAGMENTS: tuple[str, ...] = (
    "seed",
    "arrival_time",
    "burned",
    "perimeter",
    "fuel_multiplier",
    "spread_multiplier",
    "r0_base",
    "residence_time",
    "slope_coeff",
    "wind_coeff",
    "lb_coeff",
    "p_detect",
    "detect_ref",
    "false_positive",
    "is_fp",
    "p_missing",
    "lambda_fire",
    "fail_radius",
    "down_duration",
    "spot_",
    "spotting",
    "true_",
    "ground_truth",
    "ignition",
    "courant",
)

#: Field names that contain a forbidden fragment but are legitimate, with the
#: reason each is allowed.  Keeping this list short and justified is the point.
KEY_ALLOWLIST: dict[str, str] = {
    "n_detections": "count of reported detections in a scan; visible by construction",
}


def _iter_json_nodes(node: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            yield here, key
            yield from _iter_json_nodes(value, here)
    elif isinstance(node, list):
        for k, value in enumerate(node):
            yield from _iter_json_nodes(value, f"{path}[{k}]")


def _check_field_name(name: str, where: str) -> list[str]:
    lowered = str(name).lower()
    if lowered in KEY_ALLOWLIST:
        return []
    return [
        f"{where}: planner-visible field {name!r} contains forbidden fragment "
        f"{fragment!r} (docs/OBSERVATION_MODEL.md#6)"
        for fragment in FORBIDDEN_KEY_FRAGMENTS
        if fragment in lowered
    ]


def _planner_visible_paths(manifest: dict) -> list[str]:
    return [
        entry["path"]
        for entry in manifest.get("files", [])
        if entry.get("visibility") == PLANNER_VISIBLE
    ]


def scan_world_for_leakage(world_dir: str | Path) -> list[str]:
    """Run every leakage attack against a completed world."""
    world_dir = Path(world_dir)
    manifest_path = world_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"{world_dir}: no manifest.json; cannot scan for leakage"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    findings: list[str] = []
    visible = _planner_visible_paths(manifest)

    nature_params = _load_json(world_dir / "truth/nature_params.json")
    seeds = nature_params.get("seeds", {}) if nature_params else {}
    seed_values = {int(seeds.get("master_seed", -1))} | {
        int(v) for v in (seeds.get("derived_stream_seeds") or {}).values()
    }
    seed_values.discard(-1)

    findings += _scan_names_and_seeds(world_dir, visible, seed_values)
    findings += _scan_rasters(world_dir, visible)
    findings += _scan_identifiers(world_dir)
    return findings


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:  # pragma: no cover - corrupt world
        return {}


def _scan_names_and_seeds(
    world_dir: Path, visible: list[str], seed_values: set[int]
) -> list[str]:
    findings: list[str] = []
    seed_patterns = {
        value: re.compile(rf"(?<!\d){value}(?!\d)") for value in seed_values
    }

    for rel in visible:
        path = world_dir / rel
        if not path.exists():
            continue

        if path.suffix == ".csv":
            table = read_table(path)
            for name in table:
                findings += _check_field_name(name, rel)
            text = path.read_text(encoding="utf-8", errors="replace")
        elif path.suffix == ".json":
            payload = _load_json(path)
            for where, key in _iter_json_nodes(payload):
                findings += _check_field_name(key, f"{rel}:{where}")
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = ""

        for value, pattern in seed_patterns.items():
            if text and pattern.search(text):
                findings.append(
                    f"{rel}: contains the seed value {value} -- seeds must never "
                    "reach a planner-facing file (docs/OBSERVATION_MODEL.md#6)"
                )
        if text:
            offender = _find_instrument_name(text)
            if offender:
                findings.append(
                    f"{rel}: names the real instrument {offender!r}; sensors in "
                    "this laboratory are generic (docs/DECISIONS.md#d-002)"
                )
    return findings


def _find_instrument_name(text: str) -> str | None:
    for token in set(re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-]{2,}", text)):
        hit = looks_like_real_instrument(token)
        if hit:
            return hit
    return None


def _scan_rasters(world_dir: Path, visible: list[str]) -> list[str]:
    """No planner-visible raster may reproduce a hidden one, except the allow-list."""
    findings: list[str] = []
    hidden_arrays: dict[str, np.ndarray] = {}
    # Fire state: a planner-visible raster reproducing any of these is leakage.
    # A *constant* one is exempt, because it carries no information: a world
    # where nothing burned has an all-`inf` arrival field and an all-False
    # burned mask, and matching those reveals nothing (``docs/FAILURE_MODES.md#G-03``).
    for name in ("truth/arrival_time_min.npy", "truth/burned_mask_final.npy"):
        path = world_dir / name
        if not path.exists():
            continue
        array = np.nan_to_num(
            np.load(path, allow_pickle=False).astype(float), posinf=0.0, neginf=0.0
        )
        if np.unique(array).size > 1:
            hidden_arrays[name] = array

    for rel in visible:
        path = world_dir / rel
        if path.suffix != ".npy" or not path.exists():
            continue
        if rel not in STATIC_CONTEXT_ALLOWLIST:
            findings.append(
                f"{rel}: a planner-visible raster outside the static-context "
                f"allow-list {list(STATIC_CONTEXT_ALLOWLIST)} "
                "(docs/DECISIONS.md#d-006)"
            )
            continue
        visible_array = np.nan_to_num(
            np.load(path, allow_pickle=False).astype(float), posinf=0.0, neginf=0.0
        )
        for name, hidden in hidden_arrays.items():
            if visible_array.shape == hidden.shape and np.array_equal(visible_array, hidden):
                findings.append(
                    f"{rel}: is bit-identical to the hidden raster {name}"
                )

    findings += _check_fuel_class(world_dir)

    # The allow-listed rasters must match their truth counterparts exactly: if
    # they drifted, a consumer would be reasoning about a landscape the model
    # never used, which is a different (and quieter) kind of wrong.
    pairs = (
        ("observations/static_context/elevation_m.npy", "truth/landscape/elevation_m.npy"),
        ("observations/static_context/fuel_class.npy", "truth/landscape/fuel_class.npy"),
    )
    for vis_rel, truth_rel in pairs:
        vis_path, truth_path = world_dir / vis_rel, world_dir / truth_rel
        if vis_path.exists() and truth_path.exists():
            if not np.array_equal(
                np.load(vis_path, allow_pickle=False),
                np.load(truth_path, allow_pickle=False),
            ):
                findings.append(
                    f"{vis_rel}: does not match {truth_rel}; static context must "
                    "be the same landscape the nature model used"
                )
    return findings


def _check_fuel_class(world_dir: Path) -> list[str]:
    """The published fuel raster must be a genuine coarsening of the hidden one.

    Comparing the two rasters for equality is the wrong test.  A landscape with
    only two fuel levels (burnable and a non-burnable band) has a *lossless*
    coarsening by construction, and that is fine: knowing where the barrier is
    is knowing the terrain, which ``docs/DECISIONS.md#d-006`` explicitly allows.

    What must not happen is the continuous multiplier itself being published
    under the fuel-class name.  So the test is: the published raster is
    integer-typed, and it carries no more distinct levels than the hidden
    multiplier does.
    """
    vis_path = world_dir / "observations/static_context/fuel_class.npy"
    hid_path = world_dir / "truth/landscape/fuel_multiplier.npy"
    if not (vis_path.exists() and hid_path.exists()):
        return []
    published = np.load(vis_path, allow_pickle=False)
    hidden = np.load(hid_path, allow_pickle=False)
    findings: list[str] = []
    if not np.issubdtype(published.dtype, np.integer):
        findings.append(
            "observations/static_context/fuel_class.npy: dtype is "
            f"{published.dtype}, not an integer class label -- the continuous "
            "fuel multiplier is a hidden model parameter "
            "(docs/DECISIONS.md#d-006)"
        )
    n_published = int(np.unique(published).size)
    n_hidden = int(np.unique(hidden).size)
    if n_published > n_hidden:
        findings.append(
            "observations/static_context/fuel_class.npy: publishes "
            f"{n_published} levels from a hidden field with {n_hidden}; the "
            "class raster must be a coarsening, never a refinement"
        )
    return findings


def _scan_identifiers(world_dir: Path) -> list[str]:
    """Swept hidden values must not appear in planner-visible identifiers."""
    metadata = _load_json(world_dir / "metadata/world_metadata.json")
    summary = _load_json(world_dir / "truth/world_summary.json")
    axes = summary.get("sweep_axes", {}) if summary else {}
    if not metadata or not axes:
        return []

    identifier = " ".join(
        [
            str(metadata.get("scenario_name", "")),
            str(metadata.get("description", "")),
            " ".join(str(t) for t in metadata.get("tags", [])),
        ]
    ).lower()

    findings: list[str] = []
    for axis, value in axes.items():
        if isinstance(value, bool) or value is None:
            continue
        for rendition in _renditions(value):
            # An underscore is a separator here, not a word character:
            # "run_wind_6.0" is precisely the leak this check exists for.
            pattern = rf"(?<![0-9A-Za-z.]){re.escape(rendition)}(?![0-9A-Za-z.])"
            if rendition and re.search(pattern, identifier):
                findings.append(
                    f"metadata/world_metadata.json: the planner-visible identifier "
                    f"contains {rendition!r}, the swept hidden value of {axis!r} "
                    "(docs/DECISIONS.md#d-013)"
                )
                break
    return findings


def _renditions(value: Any) -> list[str]:
    """Plausible textual forms of a swept value."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        out = {str(value), str(int(value)) if float(value).is_integer() else ""}
        return [r.lower() for r in out if r]
    text = str(value).strip().lower()
    return [text] if len(text) >= 3 else []
