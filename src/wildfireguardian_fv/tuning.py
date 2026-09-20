"""Tuning, on validation worlds only.

Both policies are tuned, under the same protocol and with a comparable search
budget.  Tuning only the forecast-aware policy would manufacture a win; tuning
only the baseline would manufacture a loss.  The baseline is given the *larger*
grid, because it is the policy the experiment must not straw-man
(PROTOCOL.md section 5.1).

The forecast-aware policy is tuned at the **undegraded** condition
``(e = 0, delta = 0)`` and then held fixed across every error regime, so that
differences across the sweep are attributable to the forecast and not to
re-tuning (PROTOCOL.md section 4.4).

It is tuned **once per forecast mode**.  Mode A and Mode B are different
experiments -- a mechanism probe and a flagship -- and a policy tuned against a
weak forecast reads a strong one badly: it learns to lean on its observed-fire
trigger and then cannot exploit a forecast that is worth exploiting.  Carrying
Mode B's parameters into Mode A would confound "an accurate forecast is not
worth acting on" with "this policy was set up not to act on one".  Within each
mode the parameters are still fixed across the whole error sweep, which is what
section 4.4 requires.

Nothing here may touch the final split.  ``splits.note_final_split_read``
raises if it tries.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Sequence

from .degradation import DegradationSpec
from .loss import LossWeights
from .planner import ControlledPerturbationForecaster, IndependentPlanner
from .policy import BaselinePolicy, run_policy
from .policy.baseline import BufferParams
from .policy.forecast_aware import ForecastAwareParams, ForecastAwarePolicy
from .runner import make_forecast_source
from .world import ExperimentWorld

#: Baseline search grid.  6 x 3 x 2 x 4 = 144 configurations.
#:
#: The ranges are wide on purpose.  An optimum that lands on the edge of a
#: search grid means the policy was not actually optimised, and a baseline that
#: was not actually optimised is a straw man however it is described.
#: :func:`assert_interior_optimum` checks for that and fails the tuning run.
BASELINE_GRID: dict[str, tuple] = {
    "b0_m": (200.0, 400.0, 700.0, 1000.0, 1500.0, 2000.0),
    "b1_m_per_ms_per_min": (0.0, 6.0, 12.0),
    "b2_min": (10.0, 20.0),
    "route_buffer_frac": (0.05, 0.15, 0.35, 0.60),
}

#: Forecast-aware search grid.  3 x 4 x 5 x 2 = 120 configurations.
#:
#: Separate trigger and routing buffers, matching the freedom the baseline
#: grid gives (144 configurations). ``lead_min`` stops at 90 because the
#: forecast's valid window is 90 min: a larger lead cannot see further, and
#: the equivalence is visible in the leaderboard as a tie.
FORECAST_GRID: dict[str, tuple] = {
    "lead_min": (30.0, 60.0, 90.0),
    "route_buffer_m": (50.0, 150.0, 300.0, 600.0),
    "visible_threat_buffer_m": (150.0, 400.0, 700.0, 1000.0, 1400.0),
    "allow_wait": (True, False),
}


@dataclass(frozen=True)
class TuningResult:
    """The chosen configuration and the search that chose it."""

    best: dict
    best_loss: float
    n_configurations: int
    n_worlds: int
    split: str
    leaderboard: tuple[tuple[dict, float], ...]
    edge_optima: tuple[str, ...] = ()

    def as_record(self) -> dict:
        return {
            "best": self.best,
            "best_mean_loss": self.best_loss,
            "n_configurations": self.n_configurations,
            "n_worlds": self.n_worlds,
            "split": self.split,
            "top5": [
                {"config": c, "mean_loss": v} for c, v in self.leaderboard[:5]
            ],
            "edge_optima": list(self.edge_optima),
        }


def _grid_points(grid: dict[str, tuple]) -> list[dict]:
    keys = sorted(grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(grid[k] for k in keys))]


def assert_interior_optimum(result: "TuningResult", grid: dict[str, tuple]) -> list[str]:
    """Report parameters whose chosen value sits on the edge of their range.

    Returned rather than raised: an edge optimum is sometimes correct (a
    boolean, or a parameter whose effect genuinely saturates).  What must not
    happen is that it goes unnoticed, so it is written into the tuning record
    and quoted in the method report.
    """
    edges: list[str] = []
    for key, values in sorted(grid.items()):
        if len(values) < 3:
            continue
        chosen = result.best.get(key)
        if chosen in (values[0], values[-1]):
            edges.append(f"{key}={chosen} is at the edge of {list(values)}")
    return edges


def _check_split(worlds: Sequence[ExperimentWorld]) -> str:
    splits = {w.split for w in worlds}
    if splits != {"validation"}:
        raise AssertionError(
            f"tuning must use validation worlds only, got splits {sorted(splits)} "
            "(PROTOCOL.md section 3)"
        )
    return "validation"


def tune_baseline(
    worlds: Sequence[ExperimentWorld],
    weights: LossWeights = LossWeights(),
    grid: dict[str, tuple] | None = None,
) -> TuningResult:
    """Grid-search the trigger/buffer parameters on validation worlds."""
    split = _check_split(worlds)
    grid = grid or BASELINE_GRID
    points = _grid_points(grid)
    scored: list[tuple[dict, float]] = []
    for point in points:
        policy = BaselinePolicy(params=BufferParams(**point))
        losses = [run_policy(w, policy, weights).mean_loss(weights) for w in worlds]
        scored.append((point, sum(losses) / len(losses)))
    scored.sort(key=lambda kv: (kv[1], sorted(kv[0].items())))
    result = TuningResult(
        best=scored[0][0],
        best_loss=scored[0][1],
        n_configurations=len(points),
        n_worlds=len(worlds),
        split=split,
        leaderboard=tuple(scored),
        edge_optima=tuple(),
    )
    return replace(result, edge_optima=tuple(assert_interior_optimum(result, grid)))


def tune_forecast_aware(
    worlds: Sequence[ExperimentWorld],
    planner: IndependentPlanner | None = None,
    weights: LossWeights = LossWeights(),
    grid: dict[str, tuple] | None = None,
    base_params: ForecastAwareParams | None = None,
    mode: str = "INDEPENDENT_MODEL_FORECAST",
    perturber: ControlledPerturbationForecaster | None = None,
) -> TuningResult:
    """Grid-search the forecast-aware parameters at the undegraded condition.

    Args:
        mode: which forecast the policy is tuned against.  See the module
            docstring for why this is per-mode.
        perturber: required for ``CONTROLLED_PERTURBATION``.
    """
    split = _check_split(worlds)
    planner = planner or IndependentPlanner()
    perturber = perturber or ControlledPerturbationForecaster()
    grid = grid or FORECAST_GRID
    points = _grid_points(grid)
    undegraded = DegradationSpec()
    base = base_params or ForecastAwareParams()
    scored: list[tuple[dict, float]] = []
    for point in points:
        params = replace(base, **point)
        losses = []
        for w in worlds:
            policy = ForecastAwarePolicy(
                forecast_source=make_forecast_source(
                    w, mode, undegraded, planner, perturber
                ),
                params=params,
            )
            policy.reset()
            losses.append(run_policy(w, policy, weights).mean_loss(weights))
        scored.append((point, sum(losses) / len(losses)))
    scored.sort(key=lambda kv: (kv[1], sorted(str(kv[0]))))
    result = TuningResult(
        best=scored[0][0],
        best_loss=scored[0][1],
        n_configurations=len(points),
        n_worlds=len(worlds),
        split=split,
        leaderboard=tuple(scored),
        edge_optima=tuple(),
    )
    return replace(result, edge_optima=tuple(assert_interior_optimum(result, grid)))
