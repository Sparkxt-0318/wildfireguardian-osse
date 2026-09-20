"""The loss ``J(a, omega)``.  Declared before the experiment runs.

Deliberately simple, and deliberately **not** about mortality: this laboratory
cannot support a casualty model, so the loss counts protective-action outcomes
and the cost of taking them (PROTOCOL.md section 5).

    J = w_fail  * protection_failure
      + w_unnec * unnecessary_dispatch
      + w_expose* responder_exposure_min / EXPOSURE_SCALE_MIN
      + w_travel* travel_time_min        / TRAVEL_SCALE_MIN
      + w_res   * resource_use

``protection_failure`` is 1 when the fire reaches a resident within the horizon
and no assisted mission extracted them in time.  It is **not** a statement
about a person's fate; it is a statement about the modelled mission.

One decision unit is one resident in one world.  World-level loss is the mean
over that world's residents: residents are *nested* in a world and are not
independent replicates (PROTOCOL.md section 3).

Feasibility is evaluated per mission, independently of every other mission in
the world: this is ``INDEPENDENT_SINGLE_MISSION_FEASIBILITY``, not a
fleet-constrained population outcome, and results from it must never be called
a system protection rate (PROTOCOL.md section 5.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import LOSS_VERSION

#: Normalisation constants, minutes.  Chosen so a typical mission contributes
#: order 0.5 in its own term, keeping every term visible in a sensitivity scan.
TRAVEL_SCALE_MIN = 60.0
EXPOSURE_SCALE_MIN = 10.0


@dataclass(frozen=True)
class LossWeights:
    """Weights of ``J``.  ``v1`` values are the declared defaults."""

    w_fail: float = 1.00
    w_unnecessary: float = 0.25
    w_exposure: float = 0.15
    w_travel: float = 0.05
    w_resource: float = 0.05
    version: str = LOSS_VERSION

    def as_record(self) -> dict:
        return {
            "loss_version": self.version,
            "w_fail": self.w_fail,
            "w_unnecessary": self.w_unnecessary,
            "w_exposure": self.w_exposure,
            "w_travel": self.w_travel,
            "w_resource": self.w_resource,
            "travel_scale_min": TRAVEL_SCALE_MIN,
            "exposure_scale_min": EXPOSURE_SCALE_MIN,
        }


@dataclass(frozen=True)
class LossComponents:
    """The raw quantities that enter ``J`` for one resident in one world."""

    protection_failure: bool
    unnecessary_dispatch: bool
    dispatched: bool
    travel_time_min: float
    responder_exposure_min: float

    def value(self, weights: LossWeights = LossWeights()) -> float:
        return (
            weights.w_fail * float(self.protection_failure)
            + weights.w_unnecessary * float(self.unnecessary_dispatch)
            + weights.w_exposure * (self.responder_exposure_min / EXPOSURE_SCALE_MIN)
            + weights.w_travel * (self.travel_time_min / TRAVEL_SCALE_MIN)
            + weights.w_resource * float(self.dispatched)
        )

    def as_record(self) -> dict:
        return {
            "protection_failure": int(self.protection_failure),
            "unnecessary_dispatch": int(self.unnecessary_dispatch),
            "dispatched": int(self.dispatched),
            "travel_time_min": float(self.travel_time_min),
            "responder_exposure_min": float(self.responder_exposure_min),
            "resource_use": int(self.dispatched),
        }
