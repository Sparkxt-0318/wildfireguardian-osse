"""Export schema for ``wildfireguardian-evaluation``.

This repository owns experiment *generation*.  Formal inference -- world
bootstrap, TOST, equivalence, multiplicity correction, final confidence
intervals -- belongs to ``wildfireguardian-evaluation`` and is deliberately
**not** implemented here (``PROTOCOL.md`` section 12).

One row per ``(world, mission kind, policy, condition, wait semantics)``.  Every
row carries its full provenance block so a row can never be interpreted without
knowing which world, split, seed and code version produced it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ..storage.tables import Table

#: Column order of ``raw_outputs/evaluation_records.csv``.
RECORD_COLUMNS: tuple[str, ...] = (
    # identity and provenance
    "experiment_id", "stage", "world_id", "event_id", "archetype", "split",
    "config_hash", "master_seed", "world_generator_version",
    "planner_model_version", "policy_version", "baseline_version",
    # condition
    "policy_id", "mission_kind", "forecast_mode", "error_regime", "latency_min",
    "wait_semantics", "safety_margin_min", "direction_bias_deg", "spatial_shift_m", "rate_bias",
    "missed_spotting", "error_provenance_class",
    # forecast skill (measured independently of any policy)
    "skill_csi", "skill_iou", "skill_front_displacement_m", "skill_arrival_mae_min",
    "skill_missed_event_rate", "skill_false_alarm_rate", "skill_n_truth_cells",
    "skill_n_forecast_cells", "skill_scored", "skill_reference_epoch_min",
    # decision
    "ordered", "order_time_min", "route_id", "believed_state", "forecast_used",
    "forecast_issue_time_min",
    # outcome
    "loss", "mission_success", "mission_failed", "unnecessary_action",
    "excess_lead_hours", "responder_exposure_min", "travel_time_min",
    "resource_use", "threatened", "threat_time_min", "burned_area_ha",
    "world_flags", "failure_reason",
)

_DEFAULTS: dict[str, object] = {
    "safety_margin_min": float("nan"),
    "direction_bias_deg": float("nan"),
    "spatial_shift_m": float("nan"),
    "rate_bias": float("nan"),
    "missed_spotting": 0,
    "error_provenance_class": "n/a",
    "skill_csi": float("nan"),
    "skill_iou": float("nan"),
    "skill_front_displacement_m": float("nan"),
    "skill_arrival_mae_min": float("nan"),
    "skill_missed_event_rate": float("nan"),
    "skill_false_alarm_rate": float("nan"),
    "skill_n_truth_cells": 0,
    "skill_n_forecast_cells": 0,
    "skill_scored": 0,
    "skill_reference_epoch_min": float("nan"),
    "forecast_issue_time_min": float("nan"),
}


def _normalise(row: dict) -> dict:
    out = {}
    for column in RECORD_COLUMNS:
        value = row.get(column, _DEFAULTS.get(column, ""))
        if isinstance(value, bool):
            value = int(value)
        out[column] = value
    return out


def assert_provenance(rows: Sequence[dict]) -> None:
    """Every row must carry a complete provenance block.

    A row without it cannot be interpreted downstream, so a missing field is an
    error here rather than a puzzle later (``PROTOCOL.md`` section 13).
    """
    required = (
        "experiment_id", "world_id", "event_id", "archetype", "split",
        "config_hash", "master_seed", "policy_id", "mission_kind",
    )
    for index, row in enumerate(rows):
        missing = [k for k in required if row.get(k) in (None, "")]
        if missing:
            raise AssertionError(f"record {index} is missing provenance {missing}")


def write_records(rows: Iterable[dict], path: str | Path) -> Path:
    """Write evaluation records as CSV and return the path."""
    rows = list(rows)
    assert_provenance(rows)
    normalised = [_normalise(r) for r in rows]
    columns = {
        name: np.array([r[name] for r in normalised], dtype=object)
        for name in RECORD_COLUMNS
    }
    table = Table(columns=columns)
    path = Path(path)
    table.to_csv(path)
    return path
