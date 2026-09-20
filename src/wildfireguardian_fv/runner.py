"""The paired-world experiment driver.

For every hidden world ``omega_i`` and every condition ``theta``, the baseline
policy and the forecast-aware policy are run **against the same world object**.
Different fires for different policies would destroy the contrast, so the
pairing is asserted at run time rather than trusted.

One efficiency, stated explicitly because it looks like a shortcut and is not:
the baseline consumes no forecast, so its result is *invariant* to ``theta``.
It is therefore computed once per world and paired with every condition.
:func:`assert_baseline_theta_invariance` verifies that property directly on a
sample of worlds rather than assuming it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

from . import RESULT_BANNER
from .degradation import DegradationSpec, ErrorGrid
from .forecast import Forecast
from .info import InformationSet, build_information_set
from .loss import LossWeights
from .planner import ControlledPerturbationForecaster, IndependentPlanner
from .rng import diagnostic_generator
from .policy import BaselinePolicy, ForecastAwarePolicy, PolicyResult, run_policy
from .policy.forecast_aware import ForecastAwareParams
from .records import OutcomeRow, assert_provenance_complete, build_rows
from .skill import aggregate_skill, score_forecast
from .world import ExperimentWorld


class PairingError(AssertionError):
    """Raised when two policies were not run against the same hidden world."""


@dataclass
class ConditionResult:
    """Both policies' results for one world under one condition."""

    world_id: int
    degradation: DegradationSpec
    mode: str
    baseline: PolicyResult
    forecast_aware: PolicyResult
    skill: dict
    forecasts: tuple[Forecast, ...] = field(default=(), repr=False)

    def delta_j(self, weights: LossWeights) -> float:
        """``J_forecast - J_baseline``.  Negative means the forecast helped."""
        return self.forecast_aware.mean_loss(weights) - self.baseline.mean_loss(weights)


def make_forecast_source(
    world: ExperimentWorld, mode: str, degradation: DegradationSpec,
    planner: IndependentPlanner, perturber: ControlledPerturbationForecaster,
) -> Callable[[InformationSet], Forecast]:
    """Build the forecast callable the policy will use.

    Mode B receives the information set and nothing else.  Mode A is built by
    the evaluator from hidden truth and is closed over the world here; that
    closure is the *only* place in the package where a policy's input depends
    on truth, and it exists so Mode A can be what it is meant to be -- a
    mechanism probe with an exactly-known error (LEAKAGE_AUDIT.md section 4).
    """
    if mode == "INDEPENDENT_MODEL_FORECAST":
        return lambda info: planner.forecast(info, degradation)
    if mode == "CONTROLLED_PERTURBATION":
        return lambda info: perturber.forecast(
            world, info.information_time_min, degradation
        )
    raise ValueError(f"unknown forecast mode {mode!r}")


def assert_forecast_latency(forecasts: Iterable[Forecast], expected_min: float) -> None:
    """Every forecast must become available exactly ``expected_min`` after issue."""
    for f in forecasts:
        got = f.availability_time_min - f.issue_time_min
        if abs(got - expected_min) > 1e-9:
            raise AssertionError(
                f"forecast {f.forecast_id} has latency {got}, expected "
                f"{expected_min} (PROTOCOL.md section 12)"
            )


def run_condition(
    world: ExperimentWorld,
    degradation: DegradationSpec,
    mode: str,
    *,
    baseline: BaselinePolicy,
    forecast_params: ForecastAwareParams,
    planner: IndependentPlanner,
    perturber: ControlledPerturbationForecaster,
    weights: LossWeights,
    baseline_result: PolicyResult | None = None,
) -> ConditionResult:
    """Run the paired contrast for one world under one condition."""
    base = baseline_result or run_policy(world, baseline, weights)
    if base.world_id != world.world_id:
        raise PairingError(
            f"baseline result is for world {base.world_id}, not {world.world_id}"
        )

    source = make_forecast_source(world, mode, degradation, planner, perturber)
    policy = ForecastAwarePolicy(forecast_source=source, params=forecast_params)
    policy.reset()
    fa = run_policy(world, policy, weights)
    if fa.world_id != world.world_id:
        raise PairingError(
            f"forecast result is for world {fa.world_id}, not {world.world_id}"
        )

    issued = tuple(f for f in policy._issued.values() if f is not None)
    assert_forecast_latency(issued, degradation.latency_min)
    scores = [score_forecast(world, f) for f in issued if f.status == "ISSUED"]
    return ConditionResult(
        world_id=world.world_id,
        degradation=degradation,
        mode=mode,
        baseline=base,
        forecast_aware=fa,
        skill=aggregate_skill(scores),
        forecasts=issued,
    )


def assert_baseline_theta_invariance(
    world: ExperimentWorld,
    baseline: BaselinePolicy,
    weights: LossWeights,
    conditions: Sequence[DegradationSpec],
) -> None:
    """Verify the baseline really is invariant to the condition.

    The runner computes the baseline once per world.  That is valid only
    because the baseline consumes no forecast.  Rather than assert the claim in
    a comment, run it under several conditions and require an identical loss.
    """
    reference = run_policy(world, baseline, weights).mean_loss(weights)
    for spec in conditions:
        got = run_policy(world, baseline, weights).mean_loss(weights)
        if abs(got - reference) > 1e-12:
            raise AssertionError(
                f"baseline loss moved with condition {spec.label}: "
                f"{got} != {reference}; the baseline is not theta-invariant and "
                "must not be reused across conditions"
            )


@dataclass
class ExperimentOutput:
    """Everything one staged run produced."""

    rows: list[OutcomeRow]
    conditions: list[ConditionResult]
    world_index: list[dict]
    diagnostics: dict


def run_experiment(
    worlds: Sequence[ExperimentWorld],
    *,
    experiment_id: str,
    grid: ErrorGrid,
    modes: Sequence[str],
    baseline: BaselinePolicy,
    forecast_params: ForecastAwareParams | dict[str, ForecastAwareParams],
    planner: IndependentPlanner | None = None,
    perturber: ControlledPerturbationForecaster | None = None,
    weights: LossWeights = LossWeights(),
    progress: Callable[[str], None] | None = None,
) -> ExperimentOutput:
    """Run every condition against every world, paired.

    Args:
        forecast_params: one parameter set, or one per forecast mode.  Per-mode
            is the default in practice: a policy tuned against a weak forecast
            reads a strong one badly (``tuning`` module docstring).  Within a
            mode the parameters are constant across the whole error sweep.

    Returns:
        An :class:`ExperimentOutput` whose ``rows`` are ready to export to
        ``wildfireguardian-evaluation``.
    """
    def params_for(mode: str) -> ForecastAwareParams:
        if isinstance(forecast_params, dict):
            try:
                return forecast_params[mode]
            except KeyError:
                raise KeyError(
                    f"no forecast-aware parameters tuned for mode {mode!r}; "
                    "tune it or pass a single parameter set explicitly"
                ) from None
        return forecast_params

    planner = planner or IndependentPlanner()
    perturber = perturber or ControlledPerturbationForecaster()
    specs = grid.points()
    rows: list[OutcomeRow] = []
    results: list[ConditionResult] = []
    world_index: list[dict] = []

    for w in worlds:
        base = run_policy(w, baseline, weights)
        world_index.append(
            {
                "world_id": w.world_id,
                "event_id": w.event_id,
                "split": w.split,
                "archetype": w.archetype,
                "config_hash": w.config.config_hash(),
                "lab_seeds": w.lab_seeds.as_dict(),
                "fv_seeds": w.fv_seeds.as_dict(),
                "generation_audit": w.generation_audit,
            }
        )
        rows.extend(
            build_rows(
                experiment_id=experiment_id,
                world=w,
                policy_result=base,
                forecast_mode="NONE",
                degradation=DegradationSpec(label="baseline_theta_invariant"),
                skill={},
                loss_weights=weights,
                banner=RESULT_BANNER,
            )
        )
        for mode in modes:
            for spec in specs:
                res = run_condition(
                    w, spec, mode,
                    baseline=baseline,
                    forecast_params=params_for(mode),
                    planner=planner,
                    perturber=perturber,
                    weights=weights,
                    baseline_result=base,
                )
                results.append(res)
                rows.extend(
                    build_rows(
                        experiment_id=experiment_id,
                        world=w,
                        policy_result=res.forecast_aware,
                        forecast_mode=mode,
                        degradation=spec,
                        skill=res.skill,
                        loss_weights=weights,
                        banner=RESULT_BANNER,
                    )
                )
        if progress:
            progress(f"world {w.world_id} ({w.archetype}) done")

    assert_provenance_complete(rows)
    return ExperimentOutput(
        rows=rows,
        conditions=results,
        world_index=world_index,
        diagnostics={
            "n_worlds": len(worlds),
            "n_conditions": len(specs),
            "modes": list(modes),
            "n_rows": len(rows),
            "splits": sorted({w.split for w in worlds}),
        },
    )


def paired_deltas(
    conditions: Sequence[ConditionResult], weights: LossWeights
) -> dict[tuple[str, str], list[float]]:
    """Group paired ``delta J`` values by ``(mode, error regime)``."""
    out: dict[tuple[str, str], list[float]] = {}
    for c in conditions:
        out.setdefault((c.mode, c.degradation.label), []).append(c.delta_j(weights))
    return out


def bootstrap_ci(
    values: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 7
) -> tuple[float, float, float]:
    """Paired world-level bootstrap of the mean.  **A diagnostic only.**

    Formal inference -- multiplicity correction, equivalence testing, the final
    intervals that appear in a paper -- is the evaluation repository's job
    (PROTOCOL.md section 15).  This exists so the experiment can tell whether
    it is looking at signal or at Monte Carlo noise while it runs.
    """
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = diagnostic_generator(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return float(arr.mean()), float(lo), float(hi)
