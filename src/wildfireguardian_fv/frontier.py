"""Break-even analysis: where does ``Delta J(e, delta) = 0``?

The scientific object is the level set ``{theta : Delta J(theta) = 0}``.  It is
**not** assumed to exist, to be single-valued, to be connected, or to be
monotone.  This module therefore refuses to draw a line through a region that
does not support one.  Each slice is classified as:

``NO_CROSSING_FORECAST_BETTER``
    ``Delta J < 0`` throughout, with the whole slice resolved.
``NO_CROSSING_BASELINE_BETTER``
    ``Delta J > 0`` throughout, with the whole slice resolved.
``SINGLE_CROSSING``
    Exactly one resolved sign change.
``MULTIPLE_CROSSINGS``
    More than one.  Reported as a list of brackets, never smoothed into one.
``UNRESOLVED``
    Every point's bootstrap interval covers zero, or the sign changes only
    between points that are themselves unresolved.  The honest answer, and a
    common one at small world counts.

The intervals used here are lightweight diagnostics.  Formal uncertainty around
the level set belongs to ``wildfireguardian-evaluation``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

CROSSING_CLASSES = (
    "NO_CROSSING_FORECAST_BETTER",
    "NO_CROSSING_BASELINE_BETTER",
    "SINGLE_CROSSING",
    "MULTIPLE_CROSSINGS",
    "UNRESOLVED",
)


@dataclass(frozen=True)
class CellEstimate:
    """``Delta J`` at one grid point, with a paired bootstrap interval."""

    direction_bias_deg: float
    latency_min: float
    mean: float
    ci_lo: float
    ci_hi: float
    n_worlds: int

    @property
    def resolved(self) -> bool:
        """Whether the interval excludes zero."""
        return not (self.ci_lo <= 0.0 <= self.ci_hi)

    @property
    def sign(self) -> int:
        if not self.resolved:
            return 0
        return 1 if self.mean > 0 else -1

    def as_record(self) -> dict:
        return {
            "direction_bias_deg": self.direction_bias_deg,
            "latency_min": self.latency_min,
            "delta_j_mean": self.mean,
            "delta_j_ci_lo": self.ci_lo,
            "delta_j_ci_hi": self.ci_hi,
            "resolved": int(self.resolved),
            "n_worlds": self.n_worlds,
        }


@dataclass(frozen=True)
class SliceClassification:
    """The crossing structure of one slice through the grid."""

    axis: str            # "direction_bias_deg" or "latency_min"
    fixed_value: float
    classification: str
    crossings: tuple[tuple[float, float], ...]  # bracketing pairs on `axis`
    interpolated: tuple[float, ...]             # linear estimates inside them
    monotone: bool
    n_unresolved: int
    n_points: int
    #: True when at least one bracket spans a cell whose interval covers zero,
    #: i.e. the crossing is located less precisely than the bracket suggests.
    spans_unresolved: bool = False

    def as_record(self) -> dict:
        return {
            "axis": self.axis,
            "fixed_value": self.fixed_value,
            "classification": self.classification,
            "crossing_brackets": [list(c) for c in self.crossings],
            "interpolated_break_even": list(self.interpolated),
            "monotone": int(self.monotone),
            "n_unresolved": self.n_unresolved,
            "n_points": self.n_points,
            "bracket_spans_unresolved_cells": int(self.spans_unresolved),
        }


def classify_slice(
    axis: str, fixed_value: float, points: Sequence[CellEstimate]
) -> SliceClassification:
    """Classify the crossing structure along one slice.

    Args:
        axis: the varying axis name.
        fixed_value: the value of the other axis.
        points: the slice's estimates, in increasing order of ``axis``.
    """
    ordered = sorted(points, key=lambda p: getattr(p, axis))
    xs = [float(getattr(p, axis)) for p in ordered]
    means = [p.mean for p in ordered]
    signs = [p.sign for p in ordered]
    n_unresolved = sum(1 for s in signs if s == 0)

    diffs = np.diff(means)
    monotone = bool(np.all(diffs >= -1e-12) or np.all(diffs <= 1e-12))

    # Brackets are found between consecutive *resolved* points, not between
    # adjacent ones. A cell sitting close to zero is exactly the cell whose
    # interval is most likely to cover zero, so requiring the two sides of a
    # crossing to be adjacent would hide every frontier the experiment locates
    # precisely -- the better the grid brackets the crossing, the more surely
    # the naive rule misses it. The bracket is reported wide, spanning the
    # unresolved cells, and `spans_unresolved` says so.
    resolved_idx = [k for k, p in enumerate(ordered) if p.sign != 0]
    crossings: list[tuple[float, float]] = []
    interpolated: list[float] = []
    spans_unresolved = False
    for lo_i, hi_i in zip(resolved_idx, resolved_idx[1:]):
        a, b = ordered[lo_i], ordered[hi_i]
        if a.sign == b.sign:
            continue
        crossings.append((xs[lo_i], xs[hi_i]))
        if hi_i - lo_i > 1:
            spans_unresolved = True
        if abs(b.mean - a.mean) > 1e-12:
            frac = -a.mean / (b.mean - a.mean)
            interpolated.append(float(xs[lo_i] + frac * (xs[hi_i] - xs[lo_i])))
        else:  # pragma: no cover - defensive
            interpolated.append(float(0.5 * (xs[lo_i] + xs[hi_i])))

    if crossings:
        classification = (
            "SINGLE_CROSSING" if len(crossings) == 1 else "MULTIPLE_CROSSINGS"
        )
    elif n_unresolved == len(ordered):
        classification = "UNRESOLVED"
    else:
        resolved = [s for s in signs if s != 0]
        if all(s < 0 for s in resolved):
            classification = "NO_CROSSING_FORECAST_BETTER"
        elif all(s > 0 for s in resolved):
            classification = "NO_CROSSING_BASELINE_BETTER"
        else:  # pragma: no cover - unreachable once brackets skip unresolved
            classification = "UNRESOLVED"

    return SliceClassification(
        axis=axis,
        fixed_value=float(fixed_value),
        classification=classification,
        crossings=tuple(crossings),
        interpolated=tuple(interpolated),
        monotone=monotone,
        n_unresolved=n_unresolved,
        n_points=len(ordered),
        spans_unresolved=spans_unresolved,
    )


def estimate_frontier(cells: Sequence[CellEstimate]) -> dict:
    """Classify every row and column of the grid, and summarise.

    Returns:
        A dictionary with the per-slice classifications along both axes and a
        global summary that states, in words, what the grid does and does not
        support.
    """
    by_latency: dict[float, list[CellEstimate]] = {}
    by_direction: dict[float, list[CellEstimate]] = {}
    for c in cells:
        by_latency.setdefault(c.latency_min, []).append(c)
        by_direction.setdefault(c.direction_bias_deg, []).append(c)

    rows = [
        classify_slice("direction_bias_deg", lat, pts).as_record()
        for lat, pts in sorted(by_latency.items())
    ]
    cols = [
        classify_slice("latency_min", e, pts).as_record()
        for e, pts in sorted(by_direction.items())
    ]

    n_resolved = sum(1 for c in cells if c.resolved)
    n_forecast_better = sum(1 for c in cells if c.sign < 0)
    n_baseline_better = sum(1 for c in cells if c.sign > 0)
    any_crossing = any(r["crossing_brackets"] for r in rows + cols)
    all_monotone = all(r["monotone"] for r in rows) and all(c["monotone"] for c in cols)

    return {
        "cells": [c.as_record() for c in sorted(
            cells, key=lambda c: (c.latency_min, c.direction_bias_deg)
        )],
        "slices_over_direction_error": rows,
        "slices_over_latency": cols,
        "summary": {
            "n_cells": len(cells),
            "n_resolved": n_resolved,
            "n_unresolved": len(cells) - n_resolved,
            "n_cells_forecast_better": n_forecast_better,
            "n_cells_baseline_better": n_baseline_better,
            "frontier_exists_in_grid": bool(any_crossing),
            "all_slices_monotone": bool(all_monotone),
            "verdict": _verdict(
                len(cells), n_resolved, n_forecast_better, n_baseline_better,
                any_crossing,
            ),
        },
    }


def _verdict(
    n_cells: int, n_resolved: int, n_fc: int, n_bl: int, any_crossing: bool
) -> str:
    if n_resolved == 0:
        return (
            "UNRESOLVED_EVERYWHERE: no grid cell's paired interval excluded "
            "zero. The experiment cannot distinguish the policies at this "
            "world count; more worlds are required before any frontier claim."
        )
    if any_crossing:
        return (
            "FRONTIER_PRESENT: at least one slice changes sign between two "
            "resolved points. Crossings are reported as brackets, not as a "
            "smooth curve."
        )
    if n_fc and not n_bl:
        return (
            "NO_CROSSING_FORECAST_BETTER: every resolved cell favours the "
            "forecast-aware policy. Investigate whether the baseline is "
            "under-tuned before reporting this as a forecast benefit."
        )
    if n_bl and not n_fc:
        return (
            "NO_CROSSING_BASELINE_BETTER: every resolved cell favours the "
            "tuned baseline. This is a legitimate negative result and is "
            "reported as one."
        )
    return (  # pragma: no cover - defensive
        "MIXED_WITHOUT_LOCATED_CROSSING: both signs occur but no slice "
        "brackets a crossing; the grid is too coarse to locate a frontier."
    )
