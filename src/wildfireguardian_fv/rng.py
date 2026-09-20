"""Named random streams for the experiment layer.

Mirrors the discipline of ``wildfireguardian_osse.rng`` but uses its **own
namespace**, so that no experiment-side draw can ever perturb the hidden world::

    stream_seed = sha256("wgfv|v1|{master}|{world_id}|{stream}")[:8]

The laboratory derives its streams from ``"wgosse|v1|..."``.  The two namespaces
are disjoint, which is the mechanical form of the seed-separation requirement:
re-rolling the village layout cannot move the fire, and re-rolling the fire
cannot move the village.  ``tests/fv/test_fv_rng.py`` asserts it.

As in the laboratory: **never** call ``numpy.random`` outside this module.
``grep -rn "default_rng\\|np\\.random\\.seed" src/wildfireguardian_fv/`` must
match nothing but this file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np

#: Every stream the experiment layer is allowed to use.  Adding one is a
#: deliberate act: declare it here and document it in
#: ``experiments/forecast_value_mve/PROTOCOL.md`` section 8.
FV_STREAM_NAMES: tuple[str, ...] = (
    "world_layout_seed",   # village, road network, house placement
    "ignition_seed",       # ignition point relative to the village
    "resident_seed",       # per-resident capability assumptions
    "perturbation_seed",   # Mode A forecast degradation noise
    "policy_seed",         # policy-internal stochasticity (none used in v1)
)

#: Versioned namespace.  Changing it re-randomises every experiment world.
_FV_NAMESPACE = "wgfv|v1"


def derive_fv_seed(master_seed: int, world_id: int, stream: str, tag: str = "") -> int:
    """Derive a 64-bit seed for an experiment-side stream.

    Args:
        master_seed: the batch master seed (the same integer the laboratory
            uses, but hashed under a different namespace).
        world_id: index of the world within the batch.
        stream: one of :data:`FV_STREAM_NAMES`.
        tag: optional sub-stream label.  A quantity whose *number of draws* can
            vary needs its own sub-stream, or it shifts everything drawn after
            it (same argument as ``wildfireguardian_osse.rng.derive_seed``).

    Returns:
        A 64-bit unsigned integer seed.

    Raises:
        ValueError: if ``stream`` is not declared.
    """
    if stream not in FV_STREAM_NAMES:
        raise ValueError(
            f"unknown experiment stream {stream!r}; declare it in "
            "rng.FV_STREAM_NAMES and document it (PROTOCOL.md section 8)"
        )
    payload = f"{_FV_NAMESPACE}|{int(master_seed)}|{int(world_id)}|{stream}"
    if tag:
        payload = f"{payload}|{tag}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


@dataclass(frozen=True)
class FvSeedRegistry:
    """The experiment-side seeds for one world.

    These are **evaluator-only quantities**.  They are recorded in the run
    manifest and must never enter an :class:`~wildfireguardian_fv.info.InformationSet`
    (``tests/fv/test_information_set.py::test_no_seed_value_is_planner_visible``).
    """

    master_seed: int
    world_id: int
    seeds: Mapping[str, int] = field(repr=False)

    @classmethod
    def build(cls, master_seed: int, world_id: int = 0) -> "FvSeedRegistry":
        return cls(
            master_seed=int(master_seed),
            world_id=int(world_id),
            seeds={
                s: derive_fv_seed(master_seed, world_id, s) for s in FV_STREAM_NAMES
            },
        )

    def generator(self, stream: str, tag: str = "") -> np.random.Generator:
        """Return a fresh generator for ``stream`` (optionally sub-tagged)."""
        if stream not in self.seeds:
            raise ValueError(f"unknown experiment stream {stream!r}")
        seed = (
            self.seeds[stream]
            if not tag
            else derive_fv_seed(self.master_seed, self.world_id, stream, tag)
        )
        return np.random.default_rng(np.random.SeedSequence(seed))

    def as_dict(self) -> dict[str, object]:
        return {
            "fv_master_seed": self.master_seed,
            "world_id": self.world_id,
            "derived_fv_stream_seeds": {k: int(v) for k, v in self.seeds.items()},
        }

    def all_seed_values(self) -> Iterable[int]:
        """Every integer that must never appear in a planner-facing object."""
        yield self.master_seed
        yield from (int(v) for v in self.seeds.values())


def diagnostic_generator(seed: int) -> np.random.Generator:
    """Generator for evaluator-side diagnostics (resampling, tuning order).

    Not a world stream: it never touches a world, a forecast or a policy, so it
    cannot perturb anything reproducible.  It lives here anyway so that the
    "no ``numpy.random`` outside ``rng.py``" rule stays mechanically checkable.
    """
    return np.random.default_rng(np.random.SeedSequence(int(seed)))
