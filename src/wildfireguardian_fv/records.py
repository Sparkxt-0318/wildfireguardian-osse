"""World-level outcome records, exported for ``wildfireguardian-evaluation``.

This repository owns experiment *generation*.  Formal inference -- world
bootstrap, TOST, equivalence testing, multiplicity correction, final confidence
intervals -- belongs to ``wildfireguardian-evaluation`` and is deliberately not
reimplemented here (PROTOCOL.md section 15).  What is computed here is limited
to lightweight diagnostics that the experiment needs in order to decide whether
it is working at all.

One row is one ``(world, resident, policy, condition)`` outcome.  Every row
carries its full provenance, so a row can be traced back to the world that
produced it without consulting anything else.
"""

from __future__ import annotations

import csv
import gzip
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

#: Column order of ``raw_outputs/outcomes.csv``.  Frozen: a consumer may rely
#: on it.  New columns are appended, never inserted.
OUTCOME_COLUMNS: tuple[str, ...] = (
    # identity and provenance
    "experiment_id",
    "world_id",
    "event_id",
    "split",
    "archetype",
    "resident_id",
    "policy_id",
    "forecast_mode",
    "error_regime",
    "direction_bias_deg",
    "latency_min",
    "rate_bias_factor",
    "missed_spotting",
    # forecast skill (world level, repeated on each of the world's rows)
    "forecast_csi",
    "forecast_pod",
    "forecast_far",
    "forecast_missed_event_rate",
    "forecast_front_displacement_m",
    "forecast_arrival_mae_min",
    "forecast_arrival_bias_min",
    "forecast_n_scored",
    # decision and outcome
    "action",
    "decision_time_min",
    "reason",
    "belief_feasible",
    "mission_success",
    "failure_reason",
    "outcome_state",
    "self_evacuation_state",
    "threatened",
    "truth_arrival_at_house_min",
    "n_wait_steps",
    # loss and its components
    "loss",
    "protection_failure",
    "unnecessary_dispatch",
    "dispatched",
    "travel_time",
    "responder_exposure",
    "resource_use",
    # context
    "burned_area_ha",
    "wind_speed_ms",
    "wind_dir_deg",
    "wind_shift",
    "spotting_enabled",
    "feasibility_mode",
    "adapter_id",
    "banner",
)


@dataclass(frozen=True)
class OutcomeRow:
    """One exported outcome.  Constructed only by :func:`build_rows`."""

    values: dict[str, Any]

    def as_list(self) -> list[Any]:
        return [self.values.get(c, "") for c in OUTCOME_COLUMNS]


def build_rows(
    *,
    experiment_id: str,
    world,
    policy_result,
    forecast_mode: str,
    degradation,
    skill: dict,
    loss_weights,
    banner: str,
) -> list[OutcomeRow]:
    """Turn one policy run over one world into exported rows."""
    audit = world.generation_audit
    base = {
        "experiment_id": experiment_id,
        "world_id": world.world_id,
        "event_id": world.event_id,
        "split": world.split,
        "archetype": world.archetype,
        "policy_id": policy_result.policy_id,
        "forecast_mode": forecast_mode,
        "burned_area_ha": round(float(audit["burned_area_ha"]), 3),
        "wind_speed_ms": round(float(audit["wind_speed_ms"]), 3),
        "wind_dir_deg": round(float(audit["wind_dir_deg"]), 3),
        "wind_shift": int(audit["wind_shift"] is not None),
        "spotting_enabled": int(bool(audit["spotting_enabled"])),
        "feasibility_mode": "INDEPENDENT_SINGLE_MISSION_FEASIBILITY",
        "adapter_id": policy_result.diagnostics.get("adapter_id", ""),
        "banner": banner,
    }
    base.update(degradation.as_record())
    base.update({k: v for k, v in skill.items()})

    rows: list[OutcomeRow] = []
    for t in policy_result.traces:
        values = dict(base)
        values.update(
            {
                "resident_id": t.resident_id,
                "action": t.action,
                "decision_time_min": (
                    "" if t.decision_time_min is None else round(t.decision_time_min, 3)
                ),
                "reason": t.reason,
                "belief_feasible": int(t.belief_feasible),
                "mission_success": int(t.truth_feasible),
                "failure_reason": "" if t.truth_feasible else t.truth_reason,
                "outcome_state": t.outcome_state,
                "self_evacuation_state": t.self_evacuation_state,
                "threatened": int(t.threatened),
                "truth_arrival_at_house_min": (
                    "" if t.truth_arrival_at_house_min == float("inf")
                    else round(t.truth_arrival_at_house_min, 3)
                ),
                "n_wait_steps": t.n_wait_steps,
                "loss": round(t.loss(loss_weights), 6),
                "travel_time": round(t.travel_time_min, 3),
                "responder_exposure": round(t.responder_exposure_min, 3),
            }
        )
        values.update(t.loss_components.as_record())
        rows.append(OutcomeRow(values))
    return rows


@contextmanager
def open_outcomes(path: str | Path, mode: str = "r"):
    """Open an outcome file, transparently gzipped when the suffix says so.

    A stage's rows compress about sixty-fold, which is the difference between a
    repository a stranger can clone and one they will not. ``gzip`` needs no
    library from this package and every mainstream CSV reader opens ``.csv.gz``
    directly, so the dependency-free contract in ``docs/SCOPE.md`` is kept.
    """
    path = Path(path)
    if path.suffix == ".gz":
        handle = gzip.open(path, mode + "t", newline="", encoding="utf-8")
    else:
        handle = path.open(mode, newline="", encoding="utf-8")
    try:
        yield handle
    finally:
        handle.close()


def write_outcomes(path: str | Path, rows: Iterable[OutcomeRow]) -> Path:
    """Write rows with the frozen column order, gzipping if the path says to."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_outcomes(path, "w") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(OUTCOME_COLUMNS)
        for row in rows:
            writer.writerow(row.as_list())
    return path


def read_outcomes(path: str | Path) -> list[dict]:
    """Read an outcome file back, gzipped or not."""
    with open_outcomes(path, "r") as fh:
        return list(csv.DictReader(fh))


def assert_provenance_complete(rows: Sequence[OutcomeRow]) -> None:
    """Fail loudly if any row lost its provenance.

    Required by PROTOCOL.md section 12: a row whose world, policy, regime or
    split is missing cannot be interpreted and must never be exported.
    """
    required = (
        "experiment_id", "world_id", "split", "archetype", "policy_id",
        "forecast_mode", "error_regime", "resident_id",
    )
    for k, row in enumerate(rows):
        missing = [c for c in required if row.values.get(c) in (None, "")]
        if missing:
            raise AssertionError(
                f"outcome row {k} is missing provenance fields {missing}"
            )
