"""World manifests: file inventory, checksums and visibility labels.

The manifest is how the truth/observation boundary becomes *checkable* rather
than merely conventional.  Every file carries a visibility label, and
``wg-osse validate`` fails if a planner-visible file contains anything
forbidden (``docs/OBSERVATION_MODEL.md#0``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "1.0"

#: Visibility labels.
HIDDEN = "hidden"
PLANNER_VISIBLE = "planner_visible"

#: The only planner-visible files permitted to derive from the landscape.
#: Terrain and a coarse fuel class are known before an incident and contain no
#: temporal information, so they cannot reveal the fire's future
#: (``docs/DECISIONS.md#d-006``).  Anything else under ``observations/`` must
#: come from the observation process.
STATIC_CONTEXT_ALLOWLIST: tuple[str, ...] = (
    "observations/static_context/elevation_m.npy",
    "observations/static_context/fuel_class.npy",
)


def sha256_file(path: str | Path) -> str:
    """Streaming sha256 of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ManifestBuilder:
    """Accumulates the file inventory as a world is written."""

    def __init__(
        self,
        *,
        world_id: int,
        world_dir: Path,
        scenario_name: str,
        config_hash: str,
        generator_version: str,
    ) -> None:
        self.world_id = int(world_id)
        self.world_dir = Path(world_dir)
        self.scenario_name = scenario_name
        self.config_hash = config_hash
        self.generator_version = generator_version
        self.files: list[dict[str, Any]] = []

    def add(self, relpath: str, visibility: str, description: str) -> None:
        """Record a written file.  ``relpath`` is POSIX-style, world-relative."""
        if visibility not in (HIDDEN, PLANNER_VISIBLE):
            raise ValueError(f"unknown visibility label {visibility!r}")
        full = self.world_dir / relpath
        if not full.exists():
            raise FileNotFoundError(f"manifest references a missing file: {relpath}")
        self.files.append(
            {
                "path": relpath,
                "visibility": visibility,
                "description": description,
                "bytes": full.stat().st_size,
                "sha256": sha256_file(full),
            }
        )

    def build(self, **extra: Any) -> dict[str, Any]:
        return {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "world_id": self.world_id,
            "scenario_name": self.scenario_name,
            "config_hash": self.config_hash,
            "generator_version": self.generator_version,
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "visibility_policy": {
                "hidden": "truth/ -- never readable by a planner",
                "planner_visible": "observations/ and metadata/",
                "static_context_allowlist": list(STATIC_CONTEXT_ALLOWLIST),
                "reference": "docs/OBSERVATION_MODEL.md#0",
            },
            "files": sorted(self.files, key=lambda f: f["path"]),
            **extra,
        }


def verify_manifest(world_dir: str | Path) -> list[str]:
    """Check a world against its manifest.

    Returns:
        A list of human-readable problems; empty means the world verifies.
    """
    world_dir = Path(world_dir)
    manifest_path = world_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"{world_dir}: manifest.json is missing (world is incomplete)"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{world_dir}/manifest.json: not valid JSON ({exc})"]

    problems: list[str] = []
    listed = {entry["path"] for entry in manifest.get("files", [])}

    for entry in manifest.get("files", []):
        path = world_dir / entry["path"]
        if not path.exists():
            problems.append(f"missing file listed in manifest: {entry['path']}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            problems.append(
                f"checksum mismatch for {entry['path']}: "
                f"manifest {entry['sha256'][:12]}..., actual {actual[:12]}..."
            )
        if path.stat().st_size != entry["bytes"]:
            problems.append(f"size mismatch for {entry['path']}")

    for path in sorted(world_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rel = path.relative_to(world_dir).as_posix()
        if rel not in listed:
            problems.append(f"file present but not listed in the manifest: {rel}")

    for entry in manifest.get("files", []):
        rel, vis = entry["path"], entry["visibility"]
        if rel.startswith("truth/") and vis != HIDDEN:
            problems.append(f"{rel} is under truth/ but labelled {vis!r}")
        if rel.startswith(("observations/", "metadata/")) and vis != PLANNER_VISIBLE:
            problems.append(f"{rel} is planner-facing but labelled {vis!r}")

    return problems
