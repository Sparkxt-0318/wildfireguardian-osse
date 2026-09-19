"""Incremental, crash-safe world storage.

Outputs are ``.npy``, ``.csv`` and ``.json`` only, so a consumer can read a
world without importing this package (``docs/DECISIONS.md#d-001``).
"""

from .tables import Table, read_table
from .manifest import (
    HIDDEN,
    PLANNER_VISIBLE,
    STATIC_CONTEXT_ALLOWLIST,
    ManifestBuilder,
    sha256_file,
    verify_manifest,
)
from .writer import BatchWriter, WorldWriter, write_world
from .reader import available_at, load_world

__all__ = [
    "Table",
    "read_table",
    "HIDDEN",
    "PLANNER_VISIBLE",
    "STATIC_CONTEXT_ALLOWLIST",
    "ManifestBuilder",
    "sha256_file",
    "verify_manifest",
    "BatchWriter",
    "WorldWriter",
    "write_world",
    "available_at",
    "load_world",
]
