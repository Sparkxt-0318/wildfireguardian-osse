"""Development / validation / final splits, by landscape archetype.

Splitting by *archetype* rather than by world index means no geography is
shared between the split used for tuning and the split used for the final
reading: the final worlds are a different family of landscapes, not different
draws from the same one.  That is a stronger generalisation test than a random
split, and it is deliberately the harder one.

``final`` may be read **once**, after the protocol is frozen.  The guard below
makes an accidental early read raise rather than quietly bias the result.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

SPLITS = ("development", "validation", "final")

#: Archetype -> split.  Disjoint by construction; the test suite asserts it.
ARCHETYPE_SPLIT: dict[str, str] = {
    "open_plain": "development",
    "rolling_noise": "development",
    "sloped_valley": "validation",
    "mosaic_barrier": "validation",
    "ridge_channel": "final",
    "plateau_step": "final",
}


def archetypes_for(split: str) -> list[str]:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
    return sorted(a for a, s in ARCHETYPE_SPLIT.items() if s == split)


def split_of(archetype: str) -> str:
    try:
        return ARCHETYPE_SPLIT[archetype]
    except KeyError:  # pragma: no cover - guarded by the world generator
        raise ValueError(f"unknown archetype {archetype!r}") from None


class FinalSplitViolation(AssertionError):
    """Raised when final-split worlds are touched by tuning code."""


@dataclass
class _FinalSplitGate:
    """Process-wide switch: is reading the final split currently permitted?"""

    unlocked: bool = False
    reads: int = 0


_GATE = _FinalSplitGate()


def note_final_split_read(context: str) -> None:
    """Record (and police) one read of the final split.

    Args:
        context: what is reading it, for the error message and the manifest.

    Raises:
        FinalSplitViolation: unless inside :func:`final_split_unlocked`.
    """
    if not _GATE.unlocked:
        raise FinalSplitViolation(
            f"{context} tried to use final-split worlds while the protocol was "
            "not frozen. Tuning and inspection use development and validation "
            "worlds only (PROTOCOL.md section 3)."
        )
    _GATE.reads += 1


@contextlib.contextmanager
def final_split_unlocked(reason: str):
    """Permit final-split reads for one frozen-protocol evaluation pass.

    The count of reads is reported so that a run which opened the final split
    more than once cannot claim it looked only once.
    """
    if not reason.strip():
        raise ValueError("unlocking the final split requires a written reason")
    before = _GATE.reads
    _GATE.unlocked = True
    try:
        yield
    finally:
        _GATE.unlocked = False
        _GATE.reads = before + (_GATE.reads - before)


def final_split_read_count() -> int:
    return _GATE.reads
