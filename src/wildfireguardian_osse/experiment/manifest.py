"""Run manifest: everything needed to know what produced a set of records."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import GENERATOR_VERSION, __version__
from ..missions.dispatch import DISPATCH_SEMANTICS_ID
from ..rng import STREAM_NAMES
from .loss import LOSS_VERSION
from .runner import (
    BASELINE_VERSION,
    PLANNER_MODEL_VERSION,
    POLICY_VERSION,
    RunConfig,
)
from .worlds import WORLD_GENERATOR_VERSION, world_generation_audit

PROTOCOL_VERSION = "mve-1.0.0"
OBSERVATION_MODEL_VERSION = "osse-observations-1.0.0"
NATURE_MODEL_VERSION = "osse-nature-1.0.0"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # pragma: no cover - git absent
        return "unknown"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    cfg: RunConfig, *, data_files: list[Path] | None = None, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble the run manifest required by ``PROTOCOL.md`` section 17."""
    config_blob = json.dumps(cfg.as_dict(), sort_keys=True, separators=(",", ":"))
    manifest: dict[str, Any] = {
        "experiment_id": cfg.experiment_id,
        "protocol_version": PROTOCOL_VERSION,
        "git_commit": _git_commit(),
        "package_version": __version__,
        "world_generator_version": WORLD_GENERATOR_VERSION,
        "nature_model_version": NATURE_MODEL_VERSION,
        "planner_model_version": PLANNER_MODEL_VERSION,
        "observation_model_version": OBSERVATION_MODEL_VERSION,
        "generator_version": GENERATOR_VERSION,
        "baseline_version": BASELINE_VERSION,
        "policy_version": POLICY_VERSION,
        "loss_version": LOSS_VERSION,
        "dispatch_semantics_id": DISPATCH_SEMANTICS_ID,
        "dispatch_semantics_note": (
            "Placeholder adapter, NOT wildfireguardian-assisted-dispatch. "
            "Results depend on these mission semantics."
        ),
        "seed_manifest": {
            "master_seed": cfg.master_seed,
            "streams": list(STREAM_NAMES),
            "derivation": "sha256('wgosse|v1|{master}|{world_id}|{stream}[|{tag}]')",
        },
        "config": cfg.as_dict(),
        "config_hash": hashlib.sha256(config_blob.encode("utf-8")).hexdigest(),
        "world_generation_audit": world_generation_audit(),
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_hashes": {},
    }
    for path in data_files or []:
        path = Path(path)
        if path.exists():
            manifest["data_hashes"][path.name] = _hash_file(path)
    if extra:
        manifest.update(extra)
    return manifest
