"""Baseline tuning -- on the validation split, and nowhere else.

The primary baseline must be **strong**.  A weak baseline would guarantee the
headline result and destroy the experiment, so the buffer is tuned by grid
search to minimise mean loss, using the same hidden worlds the forecast-aware
policy will face.

The `final` split is refused here, loudly.  It is evaluated once, after the
protocol is frozen; tuning on it would make every final number optimistic by an
unknown amount (``PROTOCOL.md`` sections 3 and 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..missions.dispatch import PlaceholderDispatchAdapter
from ..missions.outcomes import MissionKind
from ..policies.base import PolicyContext, run_policy
from ..policies.baseline import BaselineParams, TunedBufferBaseline
from .loss import evaluate_decision
from .runner import PreparedWorld, prepare_world
from .worlds import build_world_set

#: The grid searched.  Coarse on purpose: a finely tuned baseline would be
#: fitted to the validation worlds rather than strong in general.
BUFFER_GRID_M = (200.0, 350.0, 500.0, 700.0, 900.0)
WIND_GAIN_GRID = (0.0, 2.0, 4.0, 6.0)
TIME_BUFFER_GRID_MIN = (10.0, 20.0, 30.0)


class FinalSplitTuningRefused(RuntimeError):
    """Raised on any attempt to tune against the final split."""


@dataclass(frozen=True)
class TuningResult:
    best: BaselineParams
    table: tuple[dict, ...]
    split: str
    n_worlds: int

    def as_dict(self) -> dict:
        return {
            "split": self.split,
            "n_worlds": self.n_worlds,
            "best_params": self.best.as_dict(),
            "grid": {
                "buffer_m": list(BUFFER_GRID_M),
                "wind_gain": list(WIND_GAIN_GRID),
                "time_buffer_min": list(TIME_BUFFER_GRID_MIN),
            },
            "table": list(self.table),
        }


def _score_params(
    params: BaselineParams,
    prepared: Sequence[PreparedWorld],
    adapter: PlaceholderDispatchAdapter,
    mission_kinds: Sequence[MissionKind],
) -> float:
    losses: list[float] = []
    for item in prepared:
        for kind in mission_kinds:
            context = PolicyContext(
                view=item.view, adapter=adapter, mission_kind=kind,
                horizon_min=item.horizon_min,
            )
            decision = run_policy(TunedBufferBaseline(params), context=context)
            breakdown, _ = evaluate_decision(
                decision=decision, truth_arrival_min=item.arrival,
                geometry=item.world.geometry, adapter=adapter,
                horizon_min=item.horizon_min, threat_time_min=item.threat_time_min,
            )
            losses.append(breakdown.loss)
    return float(np.mean(losses)) if losses else float("nan")


def tune_baseline(
    *,
    split: str = "validation",
    n_worlds: int = 24,
    master_seed: int = 7717,
    mission_kinds: Sequence[MissionKind] = (
        MissionKind.SELF_EVACUATION,
        MissionKind.ASSISTED_EVACUATION,
    ),
    progress: bool = False,
) -> TuningResult:
    """Grid-search the baseline buffer on the validation split.

    Raises:
        FinalSplitTuningRefused: if ``split`` is ``"final"``.
    """
    if split == "final":
        raise FinalSplitTuningRefused(
            "the final split is evaluated once, after protocol freeze; tuning "
            "on it would make every final number optimistic by an unknown "
            "amount (PROTOCOL.md sections 3 and 13)"
        )

    worlds = build_world_set(split, n_worlds, master_seed)
    prepared = [prepare_world(w) for w in worlds]
    adapter = PlaceholderDispatchAdapter()

    table: list[dict] = []
    best_params, best_loss = None, float("inf")
    for buffer_m in BUFFER_GRID_M:
        for wind_gain in WIND_GAIN_GRID:
            for time_buffer in TIME_BUFFER_GRID_MIN:
                params = BaselineParams(
                    buffer_m=buffer_m, wind_gain=wind_gain, time_buffer_min=time_buffer
                )
                mean_loss = _score_params(params, prepared, adapter, mission_kinds)
                table.append({**params.as_dict(), "mean_loss": mean_loss})
                if mean_loss < best_loss:
                    best_params, best_loss = params, mean_loss
                if progress:
                    print(f"  {params.as_dict()} -> {mean_loss:.4f}")

    assert best_params is not None
    return TuningResult(
        best=best_params, table=tuple(table), split=split, n_worlds=len(worlds)
    )


#: Safety margins searched for the forecast-aware policy, in minutes.
#: The upper end reaches the forecast horizon (90 min) on purpose: beyond it
#: the look-ahead falls outside the forecast's validity window, where the field
#: is +inf ("not predicted to burn"), the policy always believes it is still
#: feasible, and it stops ordering altogether.  The grid has to span that
#: failure so the optimum can be seen to be interior rather than at an edge.
SAFETY_MARGIN_GRID_MIN = (0.0, 10.0, 20.0, 30.0, 45.0, 60.0, 75.0, 90.0)


def tune_forecast_margin(
    *,
    baseline_params: BaselineParams,
    split: str = "validation",
    n_worlds: int = 12,
    master_seed: int = 7717,
    progress: bool = False,
) -> dict:
    """Tune the forecast-aware policy's one free parameter, on validation.

    The margin is chosen to minimise mean loss across the **whole condition
    grid at once** -- every error level, every latency, both forecast modes,
    both mission kinds.  Tuning it per condition would let the policy see the
    error regime it is facing, which no real policy can do, and would quietly
    turn one policy into twenty-five.

    Tuning the baseline while leaving this untuned would be an asymmetry in the
    baseline's favour; the protocol asks for a fair comparison, not a
    flattering one.

    Raises:
        FinalSplitTuningRefused: if ``split`` is ``"final"``.
    """
    if split == "final":
        raise FinalSplitTuningRefused(
            "the forecast-aware policy is tuned on validation, never on final"
        )

    from .runner import RunConfig, run_experiment

    table: list[dict] = []
    best_margin, best_loss = None, float("inf")
    for margin in SAFETY_MARGIN_GRID_MIN:
        cfg = RunConfig(
            experiment_id=f"margin_tuning_{margin:.0f}",
            split=split, n_worlds=n_worlds, master_seed=master_seed, stage="tune",
            baseline_params=baseline_params,
            include_secondary_baselines=False,
            include_wait_variant=False,
            forecast_safety_margin_min=margin,
        )
        out = run_experiment(cfg)
        losses = [
            float(r["loss"])
            for r in out["rows"]
            if r["policy_id"] == "forecast_aware_feasibility"
        ]
        mean_loss = float(np.mean(losses)) if losses else float("nan")
        table.append({"safety_margin_min": margin, "mean_loss": mean_loss,
                      "n_records": len(losses)})
        if mean_loss < best_loss:
            best_margin, best_loss = margin, mean_loss
        if progress:
            print(f"  margin {margin:4.0f} min -> mean J {mean_loss:.4f}")

    return {
        "split": split,
        "n_worlds": n_worlds,
        "master_seed": master_seed,
        "grid": list(SAFETY_MARGIN_GRID_MIN),
        "best_safety_margin_min": best_margin,
        "best_mean_loss": best_loss,
        "table": table,
        "note": (
            "Chosen over the whole condition grid at once, not per condition: "
            "a policy cannot know which error regime it is facing."
        ),
    }
