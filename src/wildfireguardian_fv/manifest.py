"""The experiment manifest: everything needed to say what was run.

Written once per run, next to the outputs.  A result without its manifest is
not a result: the manifest is what lets a stranger say which code, which
worlds, which weights and which seeds produced a given number.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wildfireguardian_osse import GENERATOR_VERSION, MODEL_BANNER

from . import (
    BASELINE_VERSION,
    DEGRADATION_MODEL_VERSION,
    DISPATCH_ADAPTER_VERSION,
    FV_VERSION,
    LOSS_VERSION,
    PLANNER_MODEL_VERSION,
    POLICY_VERSION,
    RESULT_BANNER,
    WORLD_GENERATOR_VERSION,
)


def git_commit(repo_root: str | Path = ".") -> str:
    """Current commit, or ``UNKNOWN`` outside a repository.

    Never guessed: a run that cannot identify its code says so.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() or "UNKNOWN"
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "UNKNOWN"


def git_dirty(repo_root: str | Path = ".") -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return True


def config_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    experiment_id: str,
    stage: str,
    config: dict,
    seed_manifest: dict,
    world_index: list[dict],
    data_hashes: dict[str, str] | None = None,
    notes: str = "",
    repo_root: str | Path = ".",
) -> dict:
    """Assemble the run manifest (PROTOCOL.md section 9)."""
    return {
        "experiment_id": experiment_id,
        "stage": stage,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git_commit": git_commit(repo_root),
        "git_dirty": git_dirty(repo_root),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "versions": {
            "fv": FV_VERSION,
            "osse_generator": GENERATOR_VERSION,
            "world_generator": WORLD_GENERATOR_VERSION,
            "nature_model": MODEL_BANNER,
            "planner_model": PLANNER_MODEL_VERSION,
            "observation_model": GENERATOR_VERSION,
            "degradation_model": DEGRADATION_MODEL_VERSION,
            "baseline": BASELINE_VERSION,
            "policy": POLICY_VERSION,
            "loss": LOSS_VERSION,
            "dispatch_adapter": DISPATCH_ADAPTER_VERSION,
        },
        "config": config,
        "config_hash": config_hash(config),
        "seed_manifest": seed_manifest,
        "world_index": world_index,
        "data_hashes": dict(data_hashes or {}),
        "banner": RESULT_BANNER,
        "notes": notes,
    }


def write_manifest(path: str | Path, manifest: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def file_sha256(path: str | Path) -> str:
    """SHA-256 of a file's *uncompressed content*.

    For a ``.gz`` file the hash is of what it decompresses to, not of the
    archive. Gzip output is not byte-stable across implementations and
    compression levels, so hashing the container would make a manifest fail to
    verify for a reason that has nothing to do with the data.
    """
    path = Path(path)
    h = hashlib.sha256()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
