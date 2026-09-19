"""Observation time semantics.

Four times, always, for every observation record
(``docs/TIME_SEMANTICS.md``)::

    event ---> acquisition ---> processing ---> availability
      |             |                |               |
    world        sensor           product        delivery
    state        readout          generated      completed

An observation may be used only at or after its ``availability_time_min``.
The ordering invariant holds *by construction* because every offset is
non-negative, and is asserted again here so that a future change cannot break
it silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

#: Column order used by every planner-facing observation table.
TIME_COLUMNS: tuple[str, ...] = (
    "event_time_min",
    "acquisition_time_min",
    "processing_time_min",
    "availability_time_min",
)


@dataclass(frozen=True)
class ObservationTimes:
    """The four times of a single observation, in minutes since ``t0``."""

    event_time_min: float
    acquisition_time_min: float
    processing_time_min: float
    availability_time_min: float

    def __post_init__(self) -> None:
        e, a, p, v = (
            self.event_time_min,
            self.acquisition_time_min,
            self.processing_time_min,
            self.availability_time_min,
        )
        if not (e <= a <= p <= v):
            raise ValueError(
                "observation time ordering violated: expected "
                f"event <= acquisition <= processing <= availability, got "
                f"{e} <= {a} <= {p} <= {v} (docs/TIME_SEMANTICS.md)"
            )

    @property
    def total_latency_min(self) -> float:
        """Delay between the physical event and legal usability."""
        return self.availability_time_min - self.event_time_min


def build_time_arrays(
    event_time_min: np.ndarray,
    *,
    acquisition_offset_min: float,
    processing_latency_min: float,
    delivery_latency_min: float,
    jitter_min: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Vectorised construction of the four time columns.

    Args:
        event_time_min: physical event times, shape ``(n,)``.
        acquisition_offset_min: sensor readout offset, ``>= 0``.
        processing_latency_min: fixed product-generation latency, ``>= 0``.
        delivery_latency_min: fixed delivery latency, ``>= 0``.
        jitter_min: extra, **non-negative** delay per record applied to the
            processing step, shape ``(n,)``.  ``None`` means no jitter.

    Returns:
        Mapping from each name in :data:`TIME_COLUMNS` to an array.

    Raises:
        ValueError: if any offset is negative, if jitter contains a negative
            value, or if the resulting ordering is violated.
    """
    for name, value in (
        ("acquisition_offset_min", acquisition_offset_min),
        ("processing_latency_min", processing_latency_min),
        ("delivery_latency_min", delivery_latency_min),
    ):
        if value < 0:
            raise ValueError(
                f"{name} must be >= 0 so that availability can never precede the "
                f"event; got {value} (docs/TIME_SEMANTICS.md)"
            )

    event = np.asarray(event_time_min, dtype=float)
    if jitter_min is None:
        jitter = np.zeros_like(event)
    else:
        jitter = np.asarray(jitter_min, dtype=float)
        if jitter.shape != event.shape:
            raise ValueError("jitter_min must have the same shape as event_time_min")
        if np.any(jitter < 0):
            raise ValueError("latency jitter must be non-negative")

    acquisition = event + float(acquisition_offset_min)
    processing = acquisition + float(processing_latency_min) + jitter
    availability = processing + float(delivery_latency_min)

    assert_time_ordering(event, acquisition, processing, availability)
    return {
        "event_time_min": event,
        "acquisition_time_min": acquisition,
        "processing_time_min": processing,
        "availability_time_min": availability,
    }


def assert_time_ordering(
    event: np.ndarray,
    acquisition: np.ndarray,
    processing: np.ndarray,
    availability: np.ndarray,
) -> None:
    """Raise if ``event <= acquisition <= processing <= availability`` fails."""
    checks = (
        ("event <= acquisition", event, acquisition),
        ("acquisition <= processing", acquisition, processing),
        ("processing <= availability", processing, availability),
    )
    for label, lo, hi in checks:
        bad = np.asarray(lo) > np.asarray(hi)
        if np.any(bad):
            idx = int(np.argmax(bad))
            raise ValueError(
                f"observation time ordering violated ({label}) at record {idx}: "
                f"{np.asarray(lo)[idx]} > {np.asarray(hi)[idx]} "
                "(docs/TIME_SEMANTICS.md)"
            )


def parse_epoch(epoch: str) -> datetime:
    """Parse an ISO-8601 epoch into an aware UTC datetime."""
    text = epoch.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_utc(epoch: datetime, minutes: float) -> str:
    """Convert simulation minutes to an ISO-8601 UTC string (presentational)."""
    if not np.isfinite(minutes):
        return ""
    return (epoch + timedelta(minutes=float(minutes))).isoformat().replace(
        "+00:00", "Z"
    )


def snap_to_step(t_min: float, dt_min: float, horizon_min: float) -> float:
    """Snap an observation time to the nearest simulation step.

    The *snapped* time is what gets reported as ``event_time_min``: a consumer
    is told the time of the state that was actually sampled, not an idealised
    one (``docs/TIME_SEMANTICS.md#5``).
    """
    step = int(round(float(t_min) / float(dt_min)))
    step = max(0, min(step, int(round(float(horizon_min) / float(dt_min)))))
    return step * float(dt_min)
