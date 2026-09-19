"""Named, independent random streams derived from a single master seed.

Design (``docs/DECISIONS.md#d-004``)::

    stream_seed = int(sha256("wgosse|v1|{master}|{world_id}|{stream}")[:8])

Each named stream gets its own ``numpy.random.Generator``.  Streams are
independent: consuming randomness from one cannot affect another, so changing
the sensor configuration provably cannot change the hidden fire.

**Never** call ``numpy.random`` directly anywhere else in this package.  The
rule is mechanically checkable::

    grep -rn "np\\.random\\." src/   # must match nothing outside this module
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np

#: Every stream this laboratory is allowed to use.  Adding a stream is a
#: deliberate act: it must be added here and documented in
#: ``docs/NATURE_MODEL.md`` / ``docs/OBSERVATION_MODEL.md``.
STREAM_NAMES: tuple[str, ...] = (
    "master_seed",
    "nature_seed",
    "weather_seed",
    "spotting_seed",
    "sensor_seed",
    "missingness_seed",
)

#: Namespace prefix.  Changing it re-randomises every world ever generated, so
#: it is versioned and must be bumped consciously.
_DERIVATION_NAMESPACE = "wgosse|v1"


def derive_seed(master_seed: int, world_id: int, stream: str, tag: str = "") -> int:
    """Derive a 64-bit seed for ``stream`` (optionally sub-tagged).

    Args:
        master_seed: the single integer the whole batch derives from.
        world_id: index of the world within the batch (0 for a single world).
        stream: one of :data:`STREAM_NAMES`.
        tag: optional sub-stream label, e.g. a sensor id or a weather variable.
            Sub-streams of the same stream are mutually independent.

    Returns:
        A 64-bit unsigned integer seed.

    Raises:
        ValueError: if ``stream`` is not a declared stream name.

    Note:
        Sub-tagging is not cosmetic.  If two quantities shared one generator,
        the number of draws taken by the first would shift the second -- so
        lengthening the simulation horizon would change the *past* wind
        direction, silently breaking prefix causality
        (``docs/TIME_SEMANTICS.md#6``).  Every quantity whose draw count can
        vary gets its own sub-stream.
    """
    if stream not in STREAM_NAMES:
        raise ValueError(
            f"unknown random stream {stream!r}; declare it in rng.STREAM_NAMES "
            "and document it (AGENTS.md section 1)"
        )
    payload = f"{_DERIVATION_NAMESPACE}|{int(master_seed)}|{int(world_id)}|{stream}"
    if tag:
        payload = f"{payload}|{tag}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


@dataclass(frozen=True)
class SeedRegistry:
    """The full set of derived seeds for one world.

    Held by value so it can be serialised into ``truth/nature_params.json``.
    It is **hidden truth**: seeds must never reach a planner-facing file
    (``docs/OBSERVATION_MODEL.md#6``).
    """

    master_seed: int
    world_id: int
    seeds: Mapping[str, int] = field(repr=False)

    @classmethod
    def build(cls, master_seed: int, world_id: int = 0) -> "SeedRegistry":
        return cls(
            master_seed=int(master_seed),
            world_id=int(world_id),
            seeds={s: derive_seed(master_seed, world_id, s) for s in STREAM_NAMES},
        )

    def generator(self, stream: str, tag: str = "") -> np.random.Generator:
        """Return a fresh ``Generator`` for ``stream`` (optionally sub-tagged).

        Fresh every call: a caller that wants reproducible consumption must not
        share a generator across components.
        """
        if stream not in self.seeds:
            raise ValueError(f"unknown random stream {stream!r}")
        seed = (
            self.seeds[stream]
            if not tag
            else derive_seed(self.master_seed, self.world_id, stream, tag)
        )
        return np.random.default_rng(np.random.SeedSequence(seed))

    def as_dict(self) -> dict[str, object]:
        """Serialisable form.

        The user-supplied ``master_seed`` is kept separate from the *derived*
        stream seeds (one of which is itself named ``master_seed``) so that the
        two can never be confused in a saved file.
        """
        return {
            "master_seed": self.master_seed,
            "world_id": self.world_id,
            "derived_stream_seeds": {k: int(v) for k, v in self.seeds.items()},
        }

    def all_seed_values(self) -> Iterable[int]:
        """Every integer that must never appear in a planner-facing file."""
        yield self.master_seed
        yield from (int(v) for v in self.seeds.values())
