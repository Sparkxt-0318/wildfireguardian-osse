"""The paired runner.

For every hidden world, **every** policy and every condition is evaluated
against the *same* hidden future.  Different policies never see different
fires; that is what makes ``Delta J`` a paired contrast rather than a
comparison of two samples (``PROTOCOL.md`` section 19 of the brief).

Two forecast modes, with different roles:

* **Mode A** (``CONTROLLED_PERTURBATION``) sweeps the full error x latency
  grid.  It is derived from truth, so it is a mechanism probe and, at zero
  error and zero latency, the oracle reference.
* **Mode B** (``INDEPENDENT_MODEL_FORECAST``) sweeps **latency only**: its
  error is not a knob, it is whatever the structurally different model produces
  from ``D_s``.  Its position on the error axis is therefore *measured* (by the
  skill scores) rather than set.  Mode B points are overlaid on the Mode A
  surface to ask where a real model actually lands.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from ..landscape import build_elevation, build_fuels, terrain_derivatives  # noqa: F401
from ..missions.dispatch import DISPATCH_SEMANTICS_ID, PlaceholderDispatchAdapter
from ..missions.outcomes import MissionKind
from ..nature.world import simulate_nature
from ..observations.process import run_observation_process
from ..planner.controlled import make_controlled_perturbation_forecast
from ..planner.forecast import (
    ERROR_LEVELS,
    LATENCY_LEVELS_MIN,
    ErrorRegime,
    Forecast,
    ForecastProvenance,
)
from ..planner.independent import make_independent_model_forecast
from ..planner.sandbox import SealedTruth, planner_sandbox
from ..planner.skill import score_forecast
from ..planner.view import build_planner_view
from ..policies.base import (
    DECISION_START_MIN,
    PolicyContext,
    WaitSemantics,
    decision_epochs,
    run_policy,
)
from ..policies.baseline import (
    BaselineParams,
    FireBlindBaseline,
    FixedBufferBaseline,
    OracleReference,
    TunedBufferBaseline,
    WindConditionedBaseline,
)
from ..policies.forecast_aware import ForecastAwareFeasibilityPolicy
from .loss import compute_loss, evaluate_decision, threat_time
from .worlds import ExperimentWorld, build_world_set

PLANNER_MODEL_VERSION = "mve-planner-1.0.0"
POLICY_VERSION = "mve-policy-1.0.0"
BASELINE_VERSION = "mve-baseline-1.0.0"

#: How far ahead a forecast is valid.  Latency eats into this: a forecast
#: delayed by 60 minutes leaves only 30 minutes of usable lead time, which is
#: the mechanism that gives latency real teeth.
FORECAST_HORIZON_MIN = 90.0

#: Epoch at which skill is scored, so skill is comparable across worlds and
#: independent of what any policy did.
SKILL_REFERENCE_EPOCH_MIN = 60.0


@dataclass
class RunConfig:
    """One staged run of the experiment."""

    experiment_id: str
    split: str
    n_worlds: int
    master_seed: int
    stage: str = "A"
    baseline_params: BaselineParams = field(default_factory=BaselineParams)
    error_levels: Sequence[ErrorRegime] = ERROR_LEVELS
    latency_levels: Sequence[float] = LATENCY_LEVELS_MIN
    mission_kinds: Sequence[MissionKind] = (
        MissionKind.SELF_EVACUATION,
        MissionKind.ASSISTED_EVACUATION,
    )
    include_secondary_baselines: bool = True
    include_wait_variant: bool = True
    forecast_safety_margin_min: float = 90.0
    #: Additional safety margins evaluated alongside the frozen one, recorded
    #: under a distinct policy id.  These are a declared **policy-design
    #: sensitivity probe**, not competing primary policies: the frozen margin
    #: is the one policy the protocol compares against the baseline.  The
    #: aggressive (zero-margin) variant is kept because it is the only way to
    #: show that this apparatus *can* express forecast harm at all.
    extra_forecast_margins: Sequence[float] = (0.0,)
    forecast_horizon_min: float = FORECAST_HORIZON_MIN
    skill_reference_epoch_min: float = SKILL_REFERENCE_EPOCH_MIN
    world_id_offset: int = 0

    def as_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "split": self.split,
            "n_worlds": self.n_worlds,
            "master_seed": self.master_seed,
            "stage": self.stage,
            "baseline_params": self.baseline_params.as_dict(),
            "error_levels": [e.name for e in self.error_levels],
            "latency_levels_min": [float(x) for x in self.latency_levels],
            "mission_kinds": [m.value for m in self.mission_kinds],
            "forecast_horizon_min": self.forecast_horizon_min,
            "skill_reference_epoch_min": self.skill_reference_epoch_min,
            "forecast_safety_margin_min": self.forecast_safety_margin_min,
            "extra_forecast_margins": [float(m) for m in self.extra_forecast_margins],
            "dispatch_semantics_id": DISPATCH_SEMANTICS_ID,
        }


@dataclass
class PreparedWorld:
    """A world simulated once, reusable by every policy and every condition.

    Simulating the nature world once and reusing it is what makes the design
    paired: every policy below is scored against this same hidden future.
    """

    world: ExperimentWorld
    truth: Any
    observations: Any
    view: Any
    arrival: np.ndarray
    threat_time_min: float
    horizon_min: float
    epochs: list[float]


def prepare_world(world: ExperimentWorld) -> PreparedWorld:
    """Simulate one world and build its planner view."""
    truth = simulate_nature(world.config, world.seeds)
    observations = run_observation_process(world.config, truth, world.seeds)
    view = build_planner_view(
        grid=world.geometry.grid,
        geometry=world.geometry,
        horizon_min=world.config.time.horizon_min,
        elevation_m=truth.elevation_m,
        fuel_class=truth.fuels.fuel_class,
        observations=observations,
    )
    horizon = world.config.time.horizon_min
    return PreparedWorld(
        world=world,
        truth=truth,
        observations=observations,
        view=view,
        arrival=truth.arrival_time_min,
        threat_time_min=threat_time(truth.arrival_time_min, world.geometry.grid, world.geometry),
        horizon_min=horizon,
        epochs=decision_epochs(horizon),
    )


def _truncate_to_window(field: np.ndarray, valid_to_min: float) -> np.ndarray:
    """Beyond the forecast window the planner knows nothing, not 'no fire'.

    Cells the forecast does not reach within its validity window are set to
    ``+inf``.  The feasibility check then treats them as passable, so a short
    or stale forecast makes the planner *optimistic* about the far future --
    which is exactly how a stale forecast fails in practice.
    """
    out = np.array(field, dtype=float, copy=True)
    out[out > valid_to_min] = np.inf
    return out


def _newest_epoch_at_or_before(epochs: Sequence[float], t: float) -> float | None:
    candidates = [e for e in epochs if e <= t + 1e-9]
    return max(candidates) if candidates else None


class _ForecastBank:
    """Precomputed forecast fields, served with the right availability times."""

    def __init__(self, epochs: Sequence[float], horizon_min: float) -> None:
        self.epochs = list(epochs)
        self.horizon_min = float(horizon_min)
        self.mode_a: dict[str, np.ndarray] = {}
        self.mode_b: dict[float, np.ndarray | None] = {}
        self.regimes: dict[str, ErrorRegime] = {}

    def provider(
        self, mode: ForecastProvenance, regime: ErrorRegime, latency_min: float
    ) -> Callable[[float], Forecast | None]:
        """Return ``forecast_at(s)``: the newest forecast usable at ``s``."""

        def forecast_at(s_min: float) -> Forecast | None:
            issue = _newest_epoch_at_or_before(self.epochs, s_min - latency_min)
            if issue is None:
                return None
            valid_to = issue + self.horizon_min
            if mode is ForecastProvenance.CONTROLLED_PERTURBATION:
                base = self.mode_a.get(regime.name)
                if base is None:
                    return None
                field = _truncate_to_window(base, valid_to)
            else:
                base = self.mode_b.get(issue)
                if base is None:
                    return None
                field = _truncate_to_window(base, valid_to)
            return Forecast(
                arrival_time_min=field,
                issue_time_min=float(issue),
                availability_time_min=float(issue) + float(latency_min),
                valid_from_min=float(issue),
                valid_to_min=float(valid_to),
                provenance=mode,
                error_regime=regime,
            )

        return forecast_at


def _build_bank(
    world: ExperimentWorld,
    truth,
    view,
    epochs: Sequence[float],
    cfg: RunConfig,
) -> _ForecastBank:
    bank = _ForecastBank(epochs, cfg.forecast_horizon_min)

    # Mode A: the perturbed field does not depend on the issue time in the 2-D
    # sweep (no rate bias, no missed spotting), so it is computed once per
    # regime and re-served with each issue time's validity window.
    for regime in cfg.error_levels:
        bank.regimes[regime.name] = regime
        bank.mode_a[regime.name] = make_controlled_perturbation_forecast(
            truth_arrival_min=truth.arrival_time_min,
            grid=world.geometry.grid,
            origin_xy_m=world.geometry.ignition_xy_m,
            issue_time_min=epochs[0],
            horizon_min=cfg.forecast_horizon_min,
            regime=regime,
            latency_min=0.0,
            spot_events=truth.spot_events,
        ).arrival_time_min

    # Mode B: built inside the sandbox, which proves it needs no truth at all.
    with planner_sandbox():
        for s in epochs:
            forecast = make_independent_model_forecast(
                data=view.at(s),
                grid=world.geometry.grid,
                issue_time_min=s,
                horizon_min=cfg.forecast_horizon_min,
                latency_min=0.0,
            )
            bank.mode_b[s] = None if forecast is None else forecast.arrival_time_min
    return bank


def _skill_row(
    bank: _ForecastBank,
    mode: ForecastProvenance,
    regime: ErrorRegime,
    latency_min: float,
    truth_arrival: np.ndarray,
    grid,
    reference_epoch_min: float,
) -> dict:
    """Score the forecast usable at the reference epoch, independent of policy.

    The epoch is pushed later when the latency demands it: scoring at a fixed
    60 minutes would report ``NaN`` skill for every high-latency condition, and
    a condition whose skill is unscored cannot be placed on the skill-versus-
    value plot at all.  The epoch actually used is returned with the scores.
    """
    epoch = max(float(reference_epoch_min), DECISION_START_MIN + float(latency_min))
    forecast = bank.provider(mode, regime, latency_min)(epoch)
    if forecast is None:
        return {
            "skill_csi": float("nan"), "skill_iou": float("nan"),
            "skill_front_displacement_m": float("nan"),
            "skill_arrival_mae_min": float("nan"),
            "skill_missed_event_rate": float("nan"),
            "skill_false_alarm_rate": float("nan"),
            "skill_n_truth_cells": 0, "skill_n_forecast_cells": 0,
            "skill_scored": 0, "skill_reference_epoch_min": epoch,
        }
    scores = score_forecast(forecast, truth_arrival, grid).as_dict()
    scores["skill_scored"] = 1
    scores["skill_reference_epoch_min"] = epoch
    return scores


def run_experiment(cfg: RunConfig, progress: bool = False) -> dict[str, Any]:
    """Run one stage and return rows plus diagnostics."""
    worlds = build_world_set(
        cfg.split, cfg.n_worlds, cfg.master_seed, world_id_offset=cfg.world_id_offset
    )
    adapter = PlaceholderDispatchAdapter()
    rows: list[dict] = []
    world_notes: list[dict] = []
    started = time.time()

    for world in worlds:
        prepared = prepare_world(world)
        truth, observations, view = prepared.truth, prepared.observations, prepared.view
        sealed = SealedTruth(truth, f"world_{world.world_id}")
        horizon = prepared.horizon_min
        epochs = prepared.epochs
        arrival = prepared.arrival
        t_threat = prepared.threat_time_min
        bank = _build_bank(world, truth, view, epochs, cfg)

        # Paired-design fingerprint: every policy below is scored against this
        # exact field.  Asserted after the loop.
        fingerprint = float(np.nansum(np.where(np.isfinite(arrival), arrival, 0.0)))

        world_notes.append(
            {
                "world_id": world.world_id,
                "event_id": world.event_id,
                "archetype": world.archetype,
                "split": world.split,
                "threatened": bool(np.isfinite(t_threat) and t_threat <= horizon),
                "threat_time_min": float(t_threat),
                "burned_area_ha": truth.burned_area_ha(),
                "flags": list(truth.flags),
                "warnings": list(truth.warnings),
                "n_detections": len(observations.fire_detections),
                "n_mode_b_forecasts": sum(1 for v in bank.mode_b.values() if v is not None),
            }
        )

        base_provenance = {
            **world.provenance(),
            "threat_time_min": float(t_threat),
            "burned_area_ha": truth.burned_area_ha(),
            "world_flags": ";".join(truth.flags),
            "stage": cfg.stage,
            "experiment_id": cfg.experiment_id,
        }

        for mission_kind in cfg.mission_kinds:
            context = PolicyContext(
                view=view, adapter=adapter, mission_kind=mission_kind,
                horizon_min=horizon,
            )

            # ---- baselines (no forecast) ----
            baselines = [TunedBufferBaseline(cfg.baseline_params)]
            if cfg.include_secondary_baselines:
                baselines += [
                    FixedBufferBaseline(),
                    WindConditionedBaseline(),
                    FireBlindBaseline(),
                ]
            for policy in baselines:
                decision = run_policy(policy, context=context)
                breakdown, result = evaluate_decision(
                    decision=decision, truth_arrival_min=arrival,
                    geometry=world.geometry, adapter=adapter,
                    horizon_min=horizon, threat_time_min=t_threat,
                )
                rows.append(
                    _row(
                        base_provenance, policy.policy_id, mission_kind, decision,
                        breakdown, result, regime_name="no_forecast",
                        latency_min=float("nan"), mode="NONE",
                        skill={}, wait_semantics=WaitSemantics.ACT_NOW,
                    )
                )

            # ---- oracle reference (a bound, not a policy) ----
            oracle = OracleReference(arrival, adapter, world.geometry, horizon)
            best_time, best_route = oracle.best_order_time(mission_kind, epochs)
            if best_time is None:
                oracle_loss = compute_loss(
                    ordered=False, order_time_min=float("nan"), result=None,
                    threat_time_min=t_threat, horizon_min=horizon,
                    mission_kind=mission_kind, route_id="",
                )
                oracle_result = None
            else:
                from ..policies.base import PolicyDecision
                from ..missions.outcomes import FeasibilityState

                oracle_decision = PolicyDecision(
                    policy_id="oracle_reference", mission_kind=mission_kind,
                    order_time_min=best_time, route_id=best_route,
                    rationale="latest feasible order time under perfect knowledge",
                    believed_state=FeasibilityState.BOTH_FEASIBLE,
                    wait_semantics=WaitSemantics.ACT_NOW, n_epochs_evaluated=len(epochs),
                    forecast_used=False,
                )
                oracle_loss, oracle_result = evaluate_decision(
                    decision=oracle_decision, truth_arrival_min=arrival,
                    geometry=world.geometry, adapter=adapter,
                    horizon_min=horizon, threat_time_min=t_threat,
                )
            rows.append(
                _row(
                    base_provenance, "oracle_reference", mission_kind, None,
                    oracle_loss, oracle_result, regime_name="oracle",
                    latency_min=0.0, mode="ORACLE", skill={},
                    wait_semantics=WaitSemantics.ACT_NOW,
                    order_time_override=best_time,
                )
            )

            # ---- forecast-aware, Mode A: full error x latency grid ----
            for regime in cfg.error_levels:
                for latency in cfg.latency_levels:
                    skill = _skill_row(
                        bank, ForecastProvenance.CONTROLLED_PERTURBATION, regime,
                        latency, arrival, world.geometry.grid,
                        cfg.skill_reference_epoch_min,
                    )
                    variants = [WaitSemantics.ACT_NOW]
                    if cfg.include_wait_variant and regime.name in ("none", "medium"):
                        variants.append(WaitSemantics.WAIT_FOR_FORECAST)
                    for semantics in variants:
                        for margin in _margins(cfg):
                            rows.append(
                                _run_forecast_aware(
                                    bank, ForecastProvenance.CONTROLLED_PERTURBATION,
                                    regime, latency, context, cfg, arrival,
                                    world, adapter, horizon, t_threat,
                                    base_provenance, skill, semantics, margin,
                                )
                            )

            # ---- forecast-aware, Mode B: latency only, error is measured ----
            independent_regime = ErrorRegime("independent_model")
            for latency in cfg.latency_levels:
                skill = _skill_row(
                    bank, ForecastProvenance.INDEPENDENT_MODEL_FORECAST,
                    independent_regime, latency, arrival, world.geometry.grid,
                    cfg.skill_reference_epoch_min,
                )
                for margin in _margins(cfg):
                    rows.append(
                        _run_forecast_aware(
                            bank, ForecastProvenance.INDEPENDENT_MODEL_FORECAST,
                            independent_regime, latency, context, cfg, arrival,
                            world, adapter, horizon, t_threat, base_provenance,
                            skill, WaitSemantics.ACT_NOW, margin,
                        )
                    )

        after = float(np.nansum(np.where(np.isfinite(arrival), arrival, 0.0)))
        if abs(after - fingerprint) > 1e-6:
            raise AssertionError(
                f"world {world.world_id}: the hidden field changed during "
                "evaluation; policies are not being compared on the same world "
                "(PROTOCOL.md section 13)"
            )
        _ = sealed  # the wrapper exists to make truth unreachable in policies
        if progress:
            print(
                f"  world {world.world_id:04d} {world.event_id:28s} "
                f"threat={'yes' if np.isfinite(t_threat) else ' no'} rows={len(rows)}"
            )

    return {
        "rows": rows,
        "worlds": world_notes,
        "elapsed_s": time.time() - started,
        "config": cfg.as_dict(),
    }


def _margins(cfg: RunConfig) -> list[float]:
    """The frozen margin first, then any declared sensitivity probes."""
    out = [float(cfg.forecast_safety_margin_min)]
    for margin in cfg.extra_forecast_margins:
        if not any(abs(margin - m) < 1e-9 for m in out):
            out.append(float(margin))
    return out


def _policy_id_for(cfg: RunConfig, margin: float) -> str:
    """Only the frozen margin carries the primary policy id."""
    if abs(margin - float(cfg.forecast_safety_margin_min)) < 1e-9:
        return "forecast_aware_feasibility"
    return f"forecast_aware_margin_{margin:.0f}"


def _run_forecast_aware(
    bank, mode, regime, latency, context, cfg, arrival, world, adapter,
    horizon, t_threat, base_provenance, skill, semantics, margin,
) -> dict:
    policy = ForecastAwareFeasibilityPolicy(
        cfg.baseline_params, safety_margin_min=margin
    )
    policy.policy_id = _policy_id_for(cfg, margin)
    decision = run_policy(
        policy,
        context=context,
        forecast_at=bank.provider(mode, regime, latency),
        wait_semantics=semantics,
    )
    breakdown, result = evaluate_decision(
        decision=decision, truth_arrival_min=arrival, geometry=world.geometry,
        adapter=adapter, horizon_min=horizon, threat_time_min=t_threat,
    )
    return _row(
        base_provenance, policy.policy_id, context.mission_kind, decision,
        breakdown, result, regime_name=regime.name, latency_min=float(latency),
        mode=mode.value, skill=skill, wait_semantics=semantics,
        regime=regime, safety_margin_min=margin,
    )


def _row(
    provenance, policy_id, mission_kind, decision, breakdown, result,
    *, regime_name, latency_min, mode, skill, wait_semantics,
    order_time_override=None, regime=None, safety_margin_min=float("nan"),
) -> dict:
    ordered = bool(breakdown.ordered)
    order_time = breakdown.order_time_min
    if order_time_override is not None:
        order_time = float(order_time_override)
    row = {
        **provenance,
        "policy_id": policy_id,
        "mission_kind": mission_kind.value,
        "forecast_mode": mode,
        "error_regime": regime_name,
        "latency_min": float(latency_min),
        "wait_semantics": wait_semantics.value,
        "safety_margin_min": float(safety_margin_min),
        "loss": breakdown.loss,
        "mission_success": int(ordered and breakdown.mission_failed == 0),
        "mission_failed": breakdown.mission_failed,
        "unnecessary_action": breakdown.unnecessary_action,
        "excess_lead_hours": breakdown.excess_lead_hours,
        "responder_exposure_min": breakdown.responder_exposure_min,
        "travel_time_min": breakdown.travel_time_min,
        "resource_use": int(
            ordered and mission_kind is MissionKind.ASSISTED_EVACUATION
        ),
        "ordered": int(ordered),
        "order_time_min": order_time,
        "threatened": breakdown.threatened,
        "failure_reason": breakdown.failure_reason,
        "route_id": breakdown.route_id,
        "believed_state": (
            decision.believed_state.value if decision is not None else "n/a"
        ),
        "forecast_used": int(decision.forecast_used) if decision is not None else 0,
        "forecast_issue_time_min": (
            decision.forecast_issue_time_min if decision is not None else float("nan")
        ),
        "planner_model_version": PLANNER_MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "baseline_version": BASELINE_VERSION,
    }
    row.update(skill)
    if regime is not None:
        row.update(regime.as_dict())
    return row
