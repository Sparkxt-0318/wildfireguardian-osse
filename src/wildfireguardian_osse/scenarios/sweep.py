"""Parameter sweeps over a base scenario.

A sweep file names a base scenario and a set of axes.  ``grid`` mode takes the
full Cartesian product; ``random`` mode samples independently per axis.

    sweep:
      mode: grid
      max_worlds: 400
      axes:
        - path: weather.wind_speed_ms
          values: [0.0, 3.0, 6.0]
        - path: nature.spread_multiplier
          values: [0.7, 1.3]

**Swept values are hidden parameters.**  They are recorded in
``truth/world_summary.json`` and must never be written into the scenario name,
description or tags, all of which are planner-visible in
``metadata/world_metadata.json`` (``docs/DECISIONS.md#d-013``).  This module
therefore refuses to touch those three fields, and the leakage scanner checks
the result independently.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

import yaml

from ..config import ConfigError, ScenarioConfig
from .library import VALIDATION_SCENARIOS

#: Fields a sweep must never vary: they are planner-visible identifiers.
FORBIDDEN_SWEEP_PATHS: tuple[str, ...] = ("name", "description", "tags")


@dataclass(frozen=True)
class SweepAxis:
    path: str
    values: list[Any]

    def __post_init__(self) -> None:
        root = self.path.split(".")[0]
        if root in FORBIDDEN_SWEEP_PATHS:
            raise ConfigError(
                f"sweep axis {self.path!r} targets a planner-visible identifier; "
                "swept values are hidden parameters and must not appear in the "
                "scenario name, description or tags (docs/DECISIONS.md#d-013)"
            )
        if not self.values:
            raise ConfigError(f"sweep axis {self.path!r} has no values")


@dataclass(frozen=True)
class SweepSpec:
    """A base scenario plus the axes to vary over it."""

    base: dict[str, Any]
    axes: list[SweepAxis] = field(default_factory=list)
    mode: str = "grid"
    max_worlds: int = 500
    n_samples: int = 0
    master_seed: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("grid", "random"):
            raise ConfigError(f"sweep.mode must be 'grid' or 'random', got {self.mode!r}")
        if self.mode == "random" and self.n_samples < 1:
            raise ConfigError("sweep.mode='random' requires sweep.n_samples >= 1")
        if self.max_worlds < 1:
            raise ConfigError("sweep.max_worlds must be >= 1")

    def grid_size(self) -> int:
        total = 1
        for axis in self.axes:
            total *= len(axis.values)
        return total


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    """Set ``a.b.c`` inside a nested dict, creating intermediate mappings."""
    parts = path.split(".")
    node = payload
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = copy.deepcopy(value)


def load_sweep(path: str | Path) -> SweepSpec:
    """Load a sweep YAML file.

    The file has a ``base`` mapping (an inline scenario) or ``base_scenario``
    (the name of a built-in validation scenario), plus a ``sweep`` block.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"base", "base_scenario", "sweep"}
    if unknown:
        raise ConfigError(f"sweep file: unknown top-level key(s) {sorted(unknown)}")

    if "base_scenario" in raw:
        base = copy.deepcopy(VALIDATION_SCENARIOS[raw["base_scenario"]])
        if isinstance(raw.get("base"), dict):
            base.update(raw["base"])
    elif isinstance(raw.get("base"), dict):
        base = copy.deepcopy(raw["base"])
    else:
        raise ConfigError("sweep file must define 'base' or 'base_scenario'")

    block = raw.get("sweep") or {}
    unknown = set(block) - {"mode", "axes", "max_worlds", "n_samples", "master_seed"}
    if unknown:
        raise ConfigError(f"sweep: unknown key(s) {sorted(unknown)}")

    axes = [
        SweepAxis(path=a["path"], values=list(a["values"])) for a in block.get("axes", [])
    ]
    return SweepSpec(
        base=base,
        axes=axes,
        mode=str(block.get("mode", "grid")),
        max_worlds=int(block.get("max_worlds", 500)),
        n_samples=int(block.get("n_samples", 0)),
        master_seed=block.get("master_seed"),
    )


def _combinations(spec: SweepSpec) -> Iterator[Sequence[Any]]:
    if spec.mode == "grid":
        yield from itertools.product(*(axis.values for axis in spec.axes))
        return
    # random: deterministic, derived from the master seed so that the sampled
    # design is itself reproducible.  Routed through SeedRegistry like every
    # other generator in this package (``AGENTS.md#1``).
    from ..rng import SeedRegistry

    rng = SeedRegistry.build(int(spec.master_seed or 0), 0).generator(
        "master_seed", "sweep_design"
    )
    for _ in range(spec.n_samples):
        yield tuple(axis.values[int(rng.integers(len(axis.values)))] for axis in spec.axes)


def expand_sweep(spec: SweepSpec) -> list[tuple[int, ScenarioConfig]]:
    """Expand a sweep into ``(world_id, config)`` pairs.

    ``world_id`` is the position in the expansion and enters seed derivation, so
    two worlds that happen to share a parameter combination still differ.
    Expansion stops at ``max_worlds``.
    """
    out: list[tuple[int, ScenarioConfig]] = []
    for world_id, combo in enumerate(_combinations(spec)):
        if world_id >= spec.max_worlds:
            break
        payload = copy.deepcopy(spec.base)
        if spec.master_seed is not None:
            payload["master_seed"] = int(spec.master_seed)
        for axis, value in zip(spec.axes, combo):
            _set_path(payload, axis.path, value)
        out.append((world_id, ScenarioConfig.from_mapping(payload)))
    return out
