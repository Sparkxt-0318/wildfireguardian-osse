"""The primary forecast-aware policy.  One policy, not fifteen variants.

At every decision time ``s``:

1. receive ``D_s``;
2. take the most recent forecast whose availability time is at or before ``s``
   (a forecast issued at ``s - delta`` is unusable until ``s``);
3. form a belief: what has been observed, plus what is predicted;
4. assess mission feasibility against that belief;
5. choose ``ACT_NOW``, ``WAIT_FOR_FORECAST`` or ``NO_ACTION``.

The semantics are held **fixed across every error regime**.  Only the forecast
it is handed changes, which is what makes the sweep attributable to forecast
quality rather than to policy retuning.

Waiting is bounded and costly: the policy waits only while a forecast is
expected within ``max_wait_min`` *and* no threat is already visible in the
observed fire.  Every waited step is a step in which the hidden fire advanced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import POLICY_VERSION
from ..dispatch import ArrivalTimeHazard, PlaceholderDispatchAdapter
from ..forecast import Forecast
from ..info import InformationSet
from .base import Decision
from .baseline import _village_from_info
from .belief import BELIEF_CELL_SIZE_M, distance_to_detections_m, forecast_hazard


@dataclass(frozen=True)
class ForecastAwareParams:
    """Parameters of the forecast-aware policy.

    Attributes:
        lead_min: a resident is threatened if the belief predicts arrival at
            their house within this many minutes of now.
        route_buffer_m: clearance demanded of a road around an observed
            detection.
        visible_threat_buffer_m: distance from an observed detection within
            which a resident counts as *already* threatened, whatever the
            forecast says.

            These last two must be separate, for the same reason the
            baseline's trigger and routing buffers are
            (:class:`~wildfireguardian_fv.policy.baseline.BufferParams`): one
            number doing both jobs is pulled in opposite directions, and
            tuning resolves the conflict by shrinking it, which silently
            disables the trigger. Giving the baseline that freedom and not the
            forecast-aware policy would make the comparison a straw man rather
            than a test.
        allow_wait: whether ``WAIT_FOR_FORECAST`` is permitted at all.
        max_wait_min: the policy will not wait for a product further away than
            this.
        forecast_cadence_min: how often a forecast is issued.
    """

    lead_min: float = 60.0
    route_buffer_m: float = 150.0
    visible_threat_buffer_m: float = 700.0
    allow_wait: bool = True
    max_wait_min: float = 20.0
    forecast_cadence_min: float = 15.0

    def as_record(self) -> dict:
        return {
            "lead_min": self.lead_min,
            "route_buffer_m": self.route_buffer_m,
            "visible_threat_buffer_m": self.visible_threat_buffer_m,
            "allow_wait": self.allow_wait,
            "max_wait_min": self.max_wait_min,
            "forecast_cadence_min": self.forecast_cadence_min,
        }


@dataclass
class ForecastAwarePolicy:
    """Consumes forecasts supplied by a forecast source; never makes truth calls.

    Args:
        forecast_source: a callable ``(info) -> Forecast | None`` supplying the
            forecast issued *at that information time*.  The runner injects
            either the independent planner (Mode B) or the controlled
            perturbation forecaster (Mode A).  The policy itself is identical
            in both cases.
    """

    forecast_source: object
    params: ForecastAwareParams = field(default_factory=ForecastAwareParams)
    adapter: PlaceholderDispatchAdapter = field(
        default_factory=PlaceholderDispatchAdapter
    )
    cell_size_m: float = BELIEF_CELL_SIZE_M
    policy_id: str = f"forecast_aware::{POLICY_VERSION}"
    _issued: dict = field(default_factory=dict, repr=False)

    # -- forecast bookkeeping -------------------------------------------
    def _issue_if_due(self, info: InformationSet) -> None:
        """Issue a forecast on the product cadence, from this information set."""
        s = float(info.information_time_min)
        cadence = float(self.params.forecast_cadence_min)
        if abs(s / cadence - round(s / cadence)) > 1e-9:
            return
        if s in self._issued:
            return
        self._issued[s] = self.forecast_source(info)

    def usable_forecast(self, s_min: float) -> Forecast | None:
        """The most recent forecast legally usable at ``s_min``.

        Availability, not issue time, decides.  A forecast issued 40 minutes
        ago with a 60-minute latency is still not usable.
        """
        usable = [
            f
            for f in self._issued.values()
            if f is not None and f.usable_at(s_min)
        ]
        if not usable:
            return None
        return max(usable, key=lambda f: f.issue_time_min)

    def next_forecast_eta_min(self, s_min: float) -> float:
        """Minutes until the earliest not-yet-usable forecast becomes usable."""
        pending = [
            f.availability_time_min - s_min
            for f in self._issued.values()
            if f is not None and not f.usable_at(s_min)
        ]
        return min(pending) if pending else float("inf")

    def reset(self) -> None:
        """Clear issued forecasts.  Called once per world by the runner."""
        self._issued = {}

    # -- Policy protocol -------------------------------------------------
    def belief_hazard(self, info: InformationSet) -> ArrivalTimeHazard:
        self._issue_if_due(info)
        return forecast_hazard(
            info,
            self.usable_forecast(float(info.information_time_min)),
            self.params.route_buffer_m,
            self.cell_size_m,
        )

    def decide(
        self, info: InformationSet, pending: tuple[str, ...], s_min: float
    ) -> list[Decision]:
        self._issue_if_due(info)
        if not info.has_fire_evidence():
            return [Decision(rid, "NO_ACTION", "NO_FIRE_EVIDENCE") for rid in pending]

        forecast = self.usable_forecast(s_min)
        hazard = forecast_hazard(
            info, forecast, self.params.route_buffer_m, self.cell_size_m
        )
        field_ = hazard.arrival_time_min
        dist = distance_to_detections_m(info, self.cell_size_m)
        village = _village_from_info(info)
        residents = {r.resident_id: r for r in village.residents}
        eta = self.next_forecast_eta_min(s_min)
        # Used only to recognise an *already visible* threat. It never blocks
        # a road, so it is free to be generous.
        visible_buffer = self.params.visible_threat_buffer_m

        out: list[Decision] = []
        for rid in pending:
            r = residents[rid]
            j = int(np.clip(r.x_m / self.cell_size_m, 0, field_.shape[1] - 1))
            i = int(np.clip(r.y_m / self.cell_size_m, 0, field_.shape[0] - 1))
            predicted_arrival = float(field_[i, j])
            threatened = predicted_arrival <= s_min + self.params.lead_min
            visible_threat = float(dist[i, j]) <= visible_buffer

            if not threatened and not visible_threat:
                out.append(Decision(rid, "NO_ACTION", "NO_PREDICTED_THREAT"))
                continue

            if (
                forecast is None
                and self.params.allow_wait
                and not visible_threat
                and eta <= self.params.max_wait_min
            ):
                out.append(Decision(rid, "WAIT_FOR_FORECAST", "AWAITING_FORECAST"))
                continue

            outcome = self.adapter.plan_and_evaluate(
                village, hazard, rid, s_min, info.horizon_min
            )
            if outcome.feasible:
                reason = (
                    "FORECAST_PREDICTED_THREAT" if threatened else "OBSERVED_THREAT"
                )
                out.append(Decision(rid, "ACT_NOW", reason, outcome.plan))
            else:
                out.append(Decision(rid, "NO_ACTION", f"BELIEF_{outcome.reason}"))
        return out
