"""Break-even frontier estimation.

``Delta J(e, delta) = J_forecast-aware − J_baseline``, paired within worlds.

Nothing here assumes the break-even set is monotone, connected, single-valued,
convex, or that it exists.  Every sign change along the error axis is recorded,
and a latency slice is classified as one of:

```
CROSSING              exactly one sign change
MULTIPLE_CROSSINGS    more than one
NO_CROSSING           one sign throughout (the direction is recorded)
UNRESOLVED            the paired contrast is not separable from noise
```

No curve is fitted and nothing is interpolated across an ``UNRESOLVED`` band.
The separability test is a **lightweight diagnostic** -- a paired mean against
twice its standard error -- and is explicitly *not* formal inference, which
belongs to ``wildfireguardian-evaluation`` (``PROTOCOL.md`` section 12).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Sequence

import numpy as np


class CrossingKind(str, Enum):
    CROSSING = "CROSSING"
    MULTIPLE_CROSSINGS = "MULTIPLE_CROSSINGS"
    NO_CROSSING = "NO_CROSSING"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class LevelContrast:
    """Paired contrast at one ``(error level, latency)`` cell."""

    error_regime: str
    latency_min: float
    n_worlds: int
    mean_delta_j: float
    se_delta_j: float
    resolved: bool
    sign: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FrontierSlice:
    """The break-even result for one latency."""

    latency_min: float
    kind: CrossingKind
    contrasts: tuple[LevelContrast, ...]
    crossings: tuple[tuple[str, str], ...]
    note: str

    def as_dict(self) -> dict:
        return {
            "latency_min": self.latency_min,
            "kind": self.kind.value,
            "crossings": [list(c) for c in self.crossings],
            "note": self.note,
            "contrasts": [c.as_dict() for c in self.contrasts],
        }


def paired_delta(
    rows: Sequence[dict],
    *,
    policy_id: str,
    baseline_policy_id: str,
    mission_kind: str,
    forecast_mode: str,
    error_regime: str,
    latency_min: float,
    wait_semantics: str = "ACT_NOW",
) -> tuple[np.ndarray, list[int]]:
    """Per-world ``J_policy − J_baseline`` for one condition.

    Worlds are matched by ``world_id``; a world missing either side is dropped
    and reported, never silently imputed.
    """
    baseline = {
        r["world_id"]: r["loss"]
        for r in rows
        if r["policy_id"] == baseline_policy_id and r["mission_kind"] == mission_kind
    }
    deltas, ids = [], []
    for r in rows:
        if (
            r["policy_id"] != policy_id
            or r["mission_kind"] != mission_kind
            or r["forecast_mode"] != forecast_mode
            or r["error_regime"] != error_regime
            or r.get("wait_semantics", "ACT_NOW") != wait_semantics
        ):
            continue
        if not np.isclose(float(r["latency_min"]), float(latency_min)):
            continue
        if r["world_id"] not in baseline:
            continue
        deltas.append(float(r["loss"]) - float(baseline[r["world_id"]]))
        ids.append(int(r["world_id"]))
    return np.asarray(deltas, dtype=float), ids


def estimate_frontier(
    rows: Sequence[dict],
    *,
    error_levels: Sequence[str],
    latency_levels: Sequence[float],
    mission_kind: str,
    forecast_mode: str = "CONTROLLED_PERTURBATION",
    policy_id: str = "forecast_aware_feasibility",
    baseline_policy_id: str = "baseline_tuned_buffer",
    wait_semantics: str = "ACT_NOW",
) -> list[FrontierSlice]:
    """Estimate the break-even frontier, one slice per latency."""
    slices: list[FrontierSlice] = []
    for latency in latency_levels:
        contrasts: list[LevelContrast] = []
        for level in error_levels:
            deltas, _ = paired_delta(
                rows, policy_id=policy_id, baseline_policy_id=baseline_policy_id,
                mission_kind=mission_kind, forecast_mode=forecast_mode,
                error_regime=level, latency_min=latency,
                wait_semantics=wait_semantics,
            )
            n = int(deltas.size)
            if n == 0:
                contrasts.append(
                    LevelContrast(level, float(latency), 0, float("nan"),
                                  float("nan"), False, 0)
                )
                continue
            mean = float(deltas.mean())
            se = float(deltas.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
            resolved = bool(n > 1 and np.isfinite(se) and abs(mean) > 2.0 * se)
            sign = int(np.sign(mean)) if resolved else 0
            contrasts.append(
                LevelContrast(level, float(latency), n, mean, se, resolved, sign)
            )

        slices.append(_classify(float(latency), tuple(contrasts)))
    return slices


def _classify(latency_min: float, contrasts: tuple[LevelContrast, ...]) -> FrontierSlice:
    resolved = [c for c in contrasts if c.resolved]
    if len(resolved) < 2:
        return FrontierSlice(
            latency_min=latency_min,
            kind=CrossingKind.UNRESOLVED,
            contrasts=contrasts,
            crossings=(),
            note=(
                "fewer than two error levels are separable from Monte-Carlo "
                "noise at this latency; no frontier is claimed"
            ),
        )

    crossings: list[tuple[str, str]] = []
    for a, b in zip(resolved, resolved[1:]):
        if a.sign != 0 and b.sign != 0 and a.sign != b.sign:
            crossings.append((a.error_regime, b.error_regime))

    if not crossings:
        direction = "forecast-aware better" if resolved[0].sign < 0 else "baseline better"
        unresolved = [c.error_regime for c in contrasts if not c.resolved]
        note = f"no sign change across the resolved error levels ({direction})"
        if unresolved:
            note += f"; unresolved at {unresolved}"
        return FrontierSlice(latency_min, CrossingKind.NO_CROSSING, contrasts, (), note)

    kind = CrossingKind.CROSSING if len(crossings) == 1 else CrossingKind.MULTIPLE_CROSSINGS
    note = (
        "break-even bracketed between the named error levels; no interpolation "
        "is performed and nothing is claimed inside unresolved bands"
    )
    return FrontierSlice(latency_min, kind, contrasts, tuple(crossings), note)
