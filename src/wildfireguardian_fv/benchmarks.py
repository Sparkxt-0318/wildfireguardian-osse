"""Constructed benchmark validation.

Before any large run, the laboratory must be shown capable of *expressing* the
qualitative regimes the research question is about.  Five cases:

``ACCURATE_BUT_LATE``
    Identical forecast skill, more latency, less decision value.
``CRUDE_BUT_TIMELY``
    Lower conventional skill, delivered on time, at least as much value as an
    accurate-but-late forecast.
``FORECAST_HARM``
    At least one regime where acting on the forecast is worse than the tuned
    baseline.
``BASELINE_MATCH``
    At least one regime where the two are indistinguishable.
``SIMILAR_SKILL_DIFFERENT_VALUE``
    Two regimes with close conventional skill and materially different value.

These are **validation cases, not evidence about prevalence.**  A benchmark
that passes says the experiment can represent the phenomenon; it says nothing
about how often the phenomenon occurs, and the reports must not imply that it
does.  A benchmark that does not fire is reported as ``NOT_DEMONSTRATED``,
never quietly dropped.

They run on **development** worlds, in Mode A, where the error is exactly
known -- that is what makes "identical skill, different latency" constructible
at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .degradation import DegradationSpec
from .loss import LossWeights
from .runner import ConditionResult, run_condition
from .world import ExperimentWorld

BENCHMARK_NAMES = (
    "ACCURATE_BUT_LATE",
    "CRUDE_BUT_TIMELY",
    "FORECAST_HARM",
    "BASELINE_MATCH",
    "SIMILAR_SKILL_DIFFERENT_VALUE",
)

#: Conditions the benchmark suite needs.  Mode A, so skill is controllable.
BENCHMARK_CONDITIONS: dict[str, DegradationSpec] = {
    "accurate_timely": DegradationSpec(0.0, 0.0, label="bench_e0_d0"),
    "accurate_late": DegradationSpec(0.0, 60.0, label="bench_e0_d60"),
    "crude_timely": DegradationSpec(35.0, 0.0, label="bench_e35_d0"),
    "crude_late": DegradationSpec(35.0, 60.0, label="bench_e35_d60"),
    "severe_timely": DegradationSpec(55.0, 0.0, label="bench_e55_d0"),
}


@dataclass(frozen=True)
class BenchmarkOutcome:
    """The result of one benchmark case."""

    name: str
    status: str  # "DEMONSTRATED" | "NOT_DEMONSTRATED"
    detail: str
    numbers: dict

    def as_record(self) -> dict:
        return {
            "benchmark": self.name,
            "status": self.status,
            "detail": self.detail,
            "numbers": self.numbers,
        }


def _mean(values: Sequence[float]) -> float:
    vals = [v for v in values if v == v]
    return float(np.mean(vals)) if vals else float("nan")


def _summarise(results: Sequence[ConditionResult], weights: LossWeights) -> dict:
    return {
        "delta_j": _mean([r.delta_j(weights) for r in results]),
        "j_forecast": _mean([r.forecast_aware.mean_loss(weights) for r in results]),
        "j_baseline": _mean([r.baseline.mean_loss(weights) for r in results]),
        "csi": _mean([r.skill.get("forecast_csi", float("nan")) for r in results]),
        "n_worlds": len(results),
    }


def run_benchmarks(
    worlds: Sequence[ExperimentWorld],
    *,
    baseline,
    forecast_params,
    planner,
    perturber,
    weights: LossWeights = LossWeights(),
    match_tolerance: float = 0.02,
    skill_tolerance: float = 0.05,
    value_tolerance: float = 0.02,
) -> tuple[list[BenchmarkOutcome], dict]:
    """Run the five constructed cases on ``worlds`` in Mode A.

    Args:
        worlds: development worlds.
        match_tolerance: ``|Delta J|`` below which two policies are called
            indistinguishable for ``BASELINE_MATCH``.
        skill_tolerance: CSI difference below which two regimes are called
            "similar skill".
        value_tolerance: ``Delta J`` difference above which two regimes are
            called "materially different value".

    Returns:
        ``(outcomes, raw_summaries)``.
    """
    mode = "CONTROLLED_PERTURBATION"
    summaries: dict[str, dict] = {}
    for key, spec in BENCHMARK_CONDITIONS.items():
        results = [
            run_condition(
                w, spec, mode,
                baseline=baseline,
                forecast_params=forecast_params,
                planner=planner,
                perturber=perturber,
                weights=weights,
            )
            for w in worlds
        ]
        summaries[key] = _summarise(results, weights)

    out: list[BenchmarkOutcome] = []

    a, b = summaries["accurate_timely"], summaries["accurate_late"]
    same_skill = abs(a["csi"] - b["csi"]) <= skill_tolerance
    lost_value = b["delta_j"] > a["delta_j"] + 1e-9
    out.append(
        BenchmarkOutcome(
            "ACCURATE_BUT_LATE",
            "DEMONSTRATED" if (same_skill and lost_value) else "NOT_DEMONSTRATED",
            (
                f"CSI {a['csi']:.3f} -> {b['csi']:.3f} (same within "
                f"{skill_tolerance}), delta J {a['delta_j']:+.4f} -> "
                f"{b['delta_j']:+.4f}"
            ),
            {"timely": a, "late": b},
        )
    )

    c = summaries["crude_timely"]
    crude_worse_skill = c["csi"] < b["csi"] - 1e-9
    crude_not_worse_value = c["delta_j"] <= b["delta_j"] + 1e-9
    out.append(
        BenchmarkOutcome(
            "CRUDE_BUT_TIMELY",
            "DEMONSTRATED"
            if (crude_worse_skill and crude_not_worse_value)
            else "NOT_DEMONSTRATED",
            (
                f"crude/timely CSI {c['csi']:.3f} vs accurate/late "
                f"{b['csi']:.3f}; delta J {c['delta_j']:+.4f} vs "
                f"{b['delta_j']:+.4f}"
            ),
            {"crude_timely": c, "accurate_late": b},
        )
    )

    harmful = {k: v for k, v in summaries.items() if v["delta_j"] > 1e-9}
    out.append(
        BenchmarkOutcome(
            "FORECAST_HARM",
            "DEMONSTRATED" if harmful else "NOT_DEMONSTRATED",
            (
                "regimes with delta J > 0: "
                + ", ".join(f"{k} ({v['delta_j']:+.4f})" for k, v in harmful.items())
            )
            if harmful
            else "no regime in the benchmark set made the forecast-aware "
            "policy worse than the baseline",
            {k: v for k, v in summaries.items()},
        )
    )

    matched = {
        k: v for k, v in summaries.items() if abs(v["delta_j"]) <= match_tolerance
    }
    out.append(
        BenchmarkOutcome(
            "BASELINE_MATCH",
            "DEMONSTRATED" if matched else "NOT_DEMONSTRATED",
            (
                "regimes indistinguishable within "
                f"{match_tolerance}: " + ", ".join(matched)
            )
            if matched
            else f"no regime had |delta J| <= {match_tolerance}",
            {k: summaries[k] for k in matched} or dict(summaries),
        )
    )

    pairs = []
    keys = list(summaries)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            x, y = summaries[keys[i]], summaries[keys[j]]
            if (
                abs(x["csi"] - y["csi"]) <= skill_tolerance
                and abs(x["delta_j"] - y["delta_j"]) >= value_tolerance
            ):
                pairs.append((keys[i], keys[j], x, y))
    out.append(
        BenchmarkOutcome(
            "SIMILAR_SKILL_DIFFERENT_VALUE",
            "DEMONSTRATED" if pairs else "NOT_DEMONSTRATED",
            (
                "; ".join(
                    f"{p[0]} vs {p[1]}: CSI {p[2]['csi']:.3f}/{p[3]['csi']:.3f}, "
                    f"delta J {p[2]['delta_j']:+.4f}/{p[3]['delta_j']:+.4f}"
                    for p in pairs
                )
            )
            if pairs
            else "no pair of regimes had similar CSI and materially different "
            "decision value in these worlds",
            {"pairs": [[p[0], p[1]] for p in pairs]},
        )
    )
    return out, summaries
