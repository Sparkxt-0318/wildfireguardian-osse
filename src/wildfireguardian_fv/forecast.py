"""Forecast representation and its provenance labels.

A forecast here is a **future** object, never a current-state estimate
(PROTOCOL.md section 4).  Every instance carries, explicitly:

``issue_time_min``
    The information time ``s`` whose data produced it.
``availability_time_min``
    ``s + delta`` -- the forecast may not be used before this.
``valid_from_min`` / ``valid_to_min``
    The window the prediction is about.  ``valid_from_min >= issue_time_min``
    is enforced: a product that only describes the past or present is not a
    forecast and is refused at construction.
``representation``
    ``ARRIVAL_TIME_FIELD_COARSE`` in v1: a raster of predicted fire arrival
    time on a decision grid coarser than nature's.
``uncertainty``
    ``sigma_min`` raster, or ``None``.  v1 planners emit ``None``; the field
    exists so a later probabilistic planner does not change the schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: How a forecast was produced.  The flagship conclusions should rest on
#: ``INDEPENDENT_MODEL_FORECAST``; ``CONTROLLED_PERTURBATION`` is a mechanism
#: probe built by the evaluator from hidden truth and is *not* leakage-safe by
#: construction (LEAKAGE_AUDIT.md section 4).
FORECAST_MODES = ("CONTROLLED_PERTURBATION", "INDEPENDENT_MODEL_FORECAST")

#: Output representations this schema supports.
REPRESENTATIONS = ("ARRIVAL_TIME_FIELD_COARSE",)

#: Status of the forecast product itself, independent of its accuracy.
FORECAST_STATUS = (
    "ISSUED",
    "NO_FIRE_EVIDENCE",      # nothing available at s supported a prediction
    "INSUFFICIENT_EVIDENCE",  # detections exist but no motion could be inferred
)


@dataclass(frozen=True)
class Forecast:
    """A prediction of fire arrival time over a decision grid."""

    forecast_id: str
    mode: str
    status: str
    issue_time_min: float
    availability_time_min: float
    valid_from_min: float
    valid_to_min: float
    cell_size_m: float
    predicted_arrival_time_min: np.ndarray  # (ny, nx), +inf where no arrival
    representation: str = "ARRIVAL_TIME_FIELD_COARSE"
    predicted_arrival_sigma_min: np.ndarray | None = None
    provenance: tuple[str, ...] = ()
    diagnostics: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in FORECAST_MODES:
            raise ValueError(f"unknown forecast mode {self.mode!r}")
        if self.status not in FORECAST_STATUS:
            raise ValueError(f"unknown forecast status {self.status!r}")
        if self.representation not in REPRESENTATIONS:
            raise ValueError(f"unknown representation {self.representation!r}")
        if self.availability_time_min < self.issue_time_min:
            raise ValueError(
                "a forecast cannot be available before it is issued: "
                f"{self.availability_time_min} < {self.issue_time_min}"
            )
        if self.valid_from_min < self.issue_time_min:
            raise ValueError(
                "valid_from_min precedes issue_time_min: this product describes "
                "the past or present and is a state estimate, not a forecast "
                "(PROTOCOL.md section 4)"
            )
        if self.valid_to_min < self.valid_from_min:
            raise ValueError("valid_to_min precedes valid_from_min")

    @property
    def horizon_min(self) -> float:
        """Lead time of the far edge of the valid window, from issue."""
        return self.valid_to_min - self.issue_time_min

    @property
    def latency_min(self) -> float:
        return self.availability_time_min - self.issue_time_min

    def usable_at(self, t_min: float) -> bool:
        return float(t_min) >= self.availability_time_min

    def as_record(self) -> dict:
        """Provenance fields for the exported outcome row."""
        return {
            "forecast_id": self.forecast_id,
            "forecast_mode": self.mode,
            "forecast_status": self.status,
            "forecast_issue_time_min": float(self.issue_time_min),
            "forecast_availability_time_min": float(self.availability_time_min),
            "forecast_valid_from_min": float(self.valid_from_min),
            "forecast_valid_to_min": float(self.valid_to_min),
            "forecast_horizon_min": float(self.horizon_min),
            "forecast_latency_min": float(self.latency_min),
            "forecast_representation": self.representation,
            "forecast_provenance": "|".join(self.provenance),
        }


def empty_forecast(
    forecast_id: str,
    mode: str,
    status: str,
    issue_time_min: float,
    availability_time_min: float,
    valid_to_min: float,
    shape: tuple[int, int],
    cell_size_m: float,
    provenance: tuple[str, ...] = (),
    diagnostics: dict | None = None,
) -> Forecast:
    """A forecast that predicts no arrival anywhere in its valid window.

    Used when the available data supported no prediction.  It is a real
    forecast with a real (bad) skill score, not a missing value: a policy that
    receives it must still act, which is the point.
    """
    return Forecast(
        forecast_id=forecast_id,
        mode=mode,
        status=status,
        issue_time_min=float(issue_time_min),
        availability_time_min=float(availability_time_min),
        valid_from_min=float(issue_time_min),
        valid_to_min=float(valid_to_min),
        cell_size_m=float(cell_size_m),
        predicted_arrival_time_min=np.full(shape, np.inf, dtype=float),
        provenance=provenance,
        diagnostics=dict(diagnostics or {}),
    )
