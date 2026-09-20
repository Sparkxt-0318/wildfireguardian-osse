"""Constructed benchmark validation.

Five qualitative phenomena the apparatus must be able to express *before* any
large run is worth doing.  They are **validation cases, not evidence about
prevalence**: passing them shows the experiment can represent each phenomenon,
never that any of them is common in the world
(``PROTOCOL.md`` section 16).

``ACCURATE_BUT_LATE``   high skill, little or no decision value.
``CRUDE_BUT_TIMELY``    lower skill, useful action.
``FORECAST_HARM``       forecast-aware action worse than the baseline.
``BASELINE_MATCH``      the strong baseline matches the forecast-aware policy.
``SIMILAR_SKILL_DIFFERENT_VALUE``
                        two forecasts of similar conventional skill that lead
                        to materially different decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .frontier import paired_delta

#: |Delta J| below this counts as "no material difference".
NEGLIGIBLE_DELTA = 0.03
#: CSI gap below this counts as "similar conventional skill".
SIMILAR_SKILL_GAP = 0.10


@dataclass(frozen=True)
class BenchmarkOutcome:
    name: str
    status: str            # DEMONSTRATED | NOT_DEMONSTRATED
    observed: dict
    expectation: str
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "benchmark": self.name,
            "status": self.status,
            "expectation": self.expectation,
            "observed": self.observed,
            "note": self.note,
        }


#: Policy ids the benchmarks look at.  The frozen policy first; the aggressive
#: probe is included because a benchmark suite validates the **apparatus**, and
#: a phenomenon the apparatus can express only under a different policy setting
#: is still expressible -- it just is not exhibited by the frozen policy.
FORECAST_POLICY_IDS = ("forecast_aware_feasibility", "forecast_aware_margin_0")


def _mean_delta(
    rows, *, mission_kind, mode, regime, latency, policy_id="forecast_aware_feasibility"
) -> tuple[float, int]:
    deltas, _ = paired_delta(
        rows, policy_id=policy_id,
        baseline_policy_id="baseline_tuned_buffer", mission_kind=mission_kind,
        forecast_mode=mode, error_regime=regime, latency_min=latency,
    )
    return (float(deltas.mean()) if deltas.size else float("nan"), int(deltas.size))


def _best_delta_over_policies(rows, *, mission_kind, mode, regime, latency, worst=False):
    """Return ``(policy_id, mean_delta, n)`` over the forecast-aware policies."""
    best = None
    for policy_id in FORECAST_POLICY_IDS:
        delta, n = _mean_delta(
            rows, mission_kind=mission_kind, mode=mode, regime=regime,
            latency=latency, policy_id=policy_id,
        )
        if not np.isfinite(delta):
            continue
        if best is None or (delta > best[1] if worst else delta < best[1]):
            best = (policy_id, delta, n)
    return best


def _mean_skill(rows, *, mission_kind, mode, regime, latency) -> float:
    values = [
        float(r["skill_csi"])
        for r in rows
        if r["mission_kind"] == mission_kind
        and r["forecast_mode"] == mode
        and r["error_regime"] == regime
        and np.isclose(float(r["latency_min"]), latency)
        and r.get("wait_semantics", "ACT_NOW") == "ACT_NOW"
        and np.isfinite(float(r["skill_csi"]))
    ]
    return float(np.mean(values)) if values else float("nan")


def run_benchmarks(
    rows: Sequence[dict], mission_kind: str = "self_evacuation"
) -> list[BenchmarkOutcome]:
    """Evaluate the five constructed benchmarks against a run's records."""
    A = "CONTROLLED_PERTURBATION"
    B = "INDEPENDENT_MODEL_FORECAST"
    out: list[BenchmarkOutcome] = []

    # 1. Accurate but late -------------------------------------------------
    skill_late = _mean_skill(rows, mission_kind=mission_kind, mode=A, regime="none", latency=60.0)
    delta_late, n_late = _mean_delta(
        rows, mission_kind=mission_kind, mode=A, regime="none", latency=60.0
    )
    delta_prompt, _ = _mean_delta(
        rows, mission_kind=mission_kind, mode=A, regime="none", latency=0.0
    )
    demonstrated = (
        np.isfinite(delta_late)
        and np.isfinite(delta_prompt)
        and delta_late > delta_prompt + NEGLIGIBLE_DELTA
    )
    out.append(
        BenchmarkOutcome(
            "ACCURATE_BUT_LATE",
            "DEMONSTRATED" if demonstrated else "NOT_DEMONSTRATED",
            {
                "skill_csi": skill_late,
                "mean_delta_j_latency_60": delta_late,
                "mean_delta_j_latency_0": delta_prompt,
                "n_worlds": n_late,
            },
            "a perfect but delayed forecast keeps its skill and loses its value",
        )
    )

    # 2. Crude but timely --------------------------------------------------
    best = None
    for regime in ("medium", "high"):
        skill = _mean_skill(rows, mission_kind=mission_kind, mode=A, regime=regime, latency=0.0)
        delta, n = _mean_delta(
            rows, mission_kind=mission_kind, mode=A, regime=regime, latency=0.0
        )
        if np.isfinite(delta) and (best is None or delta < best[2]):
            best = (regime, skill, delta, n)
    demonstrated = best is not None and best[2] < -NEGLIGIBLE_DELTA and best[1] < 0.75
    out.append(
        BenchmarkOutcome(
            "CRUDE_BUT_TIMELY",
            "DEMONSTRATED" if demonstrated else "NOT_DEMONSTRATED",
            {
                "error_regime": None if best is None else best[0],
                "skill_csi": None if best is None else best[1],
                "mean_delta_j": None if best is None else best[2],
                "n_worlds": None if best is None else best[3],
            },
            "a degraded but prompt forecast still beats the tuned baseline",
        )
    )

    # 3. Forecast harm -----------------------------------------------------
    harm = _best_delta_over_policies(
        rows, mission_kind=mission_kind, mode=A, regime="severe", latency=0.0, worst=True
    )
    frozen_harm, _ = _mean_delta(
        rows, mission_kind=mission_kind, mode=A, regime="severe", latency=0.0
    )
    out.append(
        BenchmarkOutcome(
            "FORECAST_HARM",
            "DEMONSTRATED" if harm is not None and harm[1] > NEGLIGIBLE_DELTA
            else "NOT_DEMONSTRATED",
            {
                "error_regime": "severe",
                "worst_policy_id": None if harm is None else harm[0],
                "worst_mean_delta_j": None if harm is None else harm[1],
                "frozen_policy_mean_delta_j": frozen_harm,
                "n_worlds": None if harm is None else harm[2],
            },
            "acting on a badly wrong forecast can be worse than the tuned baseline",
            note=(
                "Expressible by the apparatus. Whether the FROZEN policy exhibits "
                "it is a separate question, answered by frozen_policy_mean_delta_j."
            ),
        )
    )

    # 4. Baseline match ----------------------------------------------------
    matches = []
    for regime in ("none", "low", "medium", "high", "severe"):
        for latency in (0.0, 5.0, 15.0, 30.0, 60.0):
            delta, n = _mean_delta(
                rows, mission_kind=mission_kind, mode=A, regime=regime, latency=latency
            )
            if np.isfinite(delta) and abs(delta) <= NEGLIGIBLE_DELTA:
                matches.append({"error_regime": regime, "latency_min": latency,
                                "mean_delta_j": delta, "n_worlds": n})
    out.append(
        BenchmarkOutcome(
            "BASELINE_MATCH",
            "DEMONSTRATED" if matches else "NOT_DEMONSTRATED",
            {"n_matching_conditions": len(matches), "examples": matches[:5]},
            "there exist conditions where the tuned baseline matches the forecast",
        )
    )

    # 5. Similar skill, different value ------------------------------------
    points = []
    for mode, regimes in ((A, ("none", "low", "medium", "high", "severe")), (B, ("independent_model",))):
        for regime in regimes:
            for latency in (0.0, 5.0, 15.0, 30.0, 60.0):
                skill = _mean_skill(
                    rows, mission_kind=mission_kind, mode=mode, regime=regime, latency=latency
                )
                for policy_id in FORECAST_POLICY_IDS:
                    delta, n = _mean_delta(
                        rows, mission_kind=mission_kind, mode=mode, regime=regime,
                        latency=latency, policy_id=policy_id,
                    )
                    if np.isfinite(skill) and np.isfinite(delta) and n > 0:
                        points.append((mode, regime, latency, skill, delta, n, policy_id))

    pair, gap = None, 0.0
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            if abs(a[3] - b[3]) <= SIMILAR_SKILL_GAP and a[6] == b[6]:
                spread = abs(a[4] - b[4])
                if spread > gap:
                    pair, gap = (a, b), spread
    demonstrated = pair is not None and gap > 4 * NEGLIGIBLE_DELTA
    out.append(
        BenchmarkOutcome(
            "SIMILAR_SKILL_DIFFERENT_VALUE",
            "DEMONSTRATED" if demonstrated else "NOT_DEMONSTRATED",
            {
                "delta_j_gap": gap,
                "condition_a": None if pair is None else {
                    "mode": pair[0][0], "error_regime": pair[0][1],
                    "latency_min": pair[0][2], "skill_csi": pair[0][3],
                    "mean_delta_j": pair[0][4], "policy_id": pair[0][6],
                },
                "condition_b": None if pair is None else {
                    "mode": pair[1][0], "error_regime": pair[1][1],
                    "latency_min": pair[1][2], "skill_csi": pair[1][3],
                    "mean_delta_j": pair[1][4], "policy_id": pair[1][6],
                },
            },
            "conventional skill alone does not determine decision value",
            note=(
                "This is the benchmark that matters most for the research "
                "question: if it is DEMONSTRATED, skill is not sufficient to "
                "predict value in this OSSE."
            ),
        )
    )
    return out
