"""Forecast representation, provenance, and the declared error regimes.

Every forecast records its issue time, its availability time, the interval it
is valid over, how it was produced and what class of error family was applied.
Nothing downstream may use a forecast without those fields
(``experiments/forecast_value_mve/PROTOCOL.md`` section 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class ForecastProvenance(str, Enum):
    """How a forecast was generated."""

    #: Perturbation of hidden truth.  A mechanism probe, derived from truth by
    #: construction, and therefore NOT a leakage-safe planner.  At zero error
    #: and zero latency it is the oracle reference.
    CONTROLLED_PERTURBATION = "CONTROLLED_PERTURBATION"
    #: A structurally different simplified model consuming D_s only.  The mode
    #: the flagship conclusions rely on.
    INDEPENDENT_MODEL_FORECAST = "INDEPENDENT_MODEL_FORECAST"


class ErrorProvenanceClass(str, Enum):
    """Where an error family's magnitude comes from.

    No family in the MVE is EMPIRICALLY_MOTIVATED or LEARNED, because no
    operational error statistics have been verified
    (``docs/ASSUMPTIONS.md#D-08`` is UNKNOWN).  No probability is placed over
    regimes; results are conditional on the regime.
    """

    TOY_MECHANISM = "TOY_MECHANISM"
    STRESS_TEST = "STRESS_TEST"
    EMPIRICALLY_MOTIVATED = "EMPIRICALLY_MOTIVATED"
    LEARNED = "LEARNED"


@dataclass(frozen=True)
class ErrorRegime:
    """One point of the controlled-degradation space ``theta``."""

    name: str
    direction_bias_deg: float = 0.0
    spatial_shift_m: float = 0.0
    rate_bias: float = 1.0
    missed_spotting: bool = False
    provenance_class: ErrorProvenanceClass = ErrorProvenanceClass.TOY_MECHANISM

    def as_dict(self) -> dict:
        return {
            "error_regime": self.name,
            "direction_bias_deg": float(self.direction_bias_deg),
            "spatial_shift_m": float(self.spatial_shift_m),
            "rate_bias": float(self.rate_bias),
            "missed_spotting": bool(self.missed_spotting),
            "error_provenance_class": self.provenance_class.value,
        }


#: The declared 1-D error axis of the MVE: a coherent direction bias paired
#: with a coherent spatial displacement.  Values are scaled to this
#: simulation's timescale, not copied from an illustrative list
#: (PROTOCOL.md section 10).
ERROR_LEVELS: tuple[ErrorRegime, ...] = (
    ErrorRegime("none", 0.0, 0.0),
    ErrorRegime("low", 10.0, 150.0),
    ErrorRegime("medium", 25.0, 350.0),
    ErrorRegime("high", 45.0, 700.0),
    ErrorRegime("severe", 80.0, 1200.0),
)

#: The declared latency axis, in minutes.
LATENCY_LEVELS_MIN: tuple[float, ...] = (0.0, 5.0, 15.0, 30.0, 60.0)


@dataclass(frozen=True)
class Forecast:
    """A predicted arrival-time raster, with its time semantics."""

    arrival_time_min: np.ndarray
    issue_time_min: float
    availability_time_min: float
    valid_from_min: float
    valid_to_min: float
    provenance: ForecastProvenance
    error_regime: ErrorRegime
    representation: str = "arrival_time_raster_min"
    uncertainty: str = "none"
    diagnostics: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.availability_time_min < self.issue_time_min - 1e-9:
            raise ValueError(
                "a forecast cannot be available before it is issued: "
                f"issue={self.issue_time_min}, "
                f"availability={self.availability_time_min}"
            )
        if self.valid_to_min < self.valid_from_min:
            raise ValueError("forecast valid_to precedes valid_from")
        if self.valid_from_min < self.issue_time_min - 1e-9:
            raise ValueError(
                "a forecast must describe times at or after its issue time; "
                "a current-state estimate is not a forecast "
                "(PROTOCOL.md section 5)"
            )

    @property
    def horizon_min(self) -> float:
        return self.valid_to_min - self.issue_time_min

    @property
    def latency_min(self) -> float:
        return self.availability_time_min - self.issue_time_min

    def usable_at(self, s_min: float) -> bool:
        return self.availability_time_min <= float(s_min) + 1e-9
