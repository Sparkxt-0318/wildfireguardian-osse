"""One experiment world: hidden truth plus the planner-visible layout.

The independent unit of the experiment is

    world = (landscape, ignition, weather sequence, nature randomness,
             village layout)

Residents and routes inside one world are **nested**, never counted as
independent worlds (PROTOCOL.md section 3).  Both policies are run against the
same :class:`ExperimentWorld` instance, which is what makes the contrast paired.

This module is evaluator-side.  It holds truth.  Nothing here may be handed to
a planner; the only export path is
:func:`wildfireguardian_fv.info.build_information_set`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from wildfireguardian_osse.config import ScenarioConfig
from wildfireguardian_osse.nature.world import NatureTruth
from wildfireguardian_osse.observations.process import ObservationBundle
from wildfireguardian_osse.rng import SeedRegistry

from .dispatch import ArrivalTimeHazard
from .rng import FvSeedRegistry
from .village import Village


@dataclass(frozen=True)
class ExperimentWorld:
    """A generated world, ready for paired policy evaluation."""

    world_id: int
    event_id: str
    split: str
    archetype: str
    config: ScenarioConfig
    lab_seeds: SeedRegistry
    fv_seeds: FvSeedRegistry
    truth: NatureTruth
    observations: ObservationBundle
    village: Village
    static_context: dict[str, np.ndarray]
    grid_meta: dict[str, Any]
    horizon_min: float
    generation_audit: dict[str, Any]

    # -- evaluator-only ---------------------------------------------------
    def truth_hazard(self) -> ArrivalTimeHazard:
        """The hidden arrival-time field, wrapped for mission evaluation.

        **Evaluation only.**  Passing this to planner-side code invalidates the
        experiment; the runner never does, and ``truth_access_guard`` is active
        while planner code runs.
        """
        return ArrivalTimeHazard(
            arrival_time_min=self.truth.arrival_time_min,
            cell_size_m=self.truth.grid.cell_size_m,
            source="HIDDEN_TRUTH",
        )

    def all_hidden_seed_values(self) -> list[int]:
        return list(self.lab_seeds.all_seed_values()) + list(
            self.fv_seeds.all_seed_values()
        )

    def burned_area_ha(self) -> float:
        return self.truth.burned_area_ha()

    def resident_arrival_times_min(self) -> dict[str, float]:
        """True fire arrival time at each house.  Scoring only."""
        hazard = self.truth_hazard()
        return {
            r.resident_id: float(hazard.arrival_at(np.array([[r.x_m, r.y_m]]))[0])
            for r in self.village.residents
        }

    def threatened_residents(self) -> set[str]:
        """Residents the fire actually reaches within the horizon.

        Used only to score "unnecessary dispatch"; no policy may see it.
        """
        return {
            rid
            for rid, t in self.resident_arrival_times_min().items()
            if np.isfinite(t) and t <= self.horizon_min
        }
