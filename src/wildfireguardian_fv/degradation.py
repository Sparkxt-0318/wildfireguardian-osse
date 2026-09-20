"""Structured forecast-error families, and where each one comes from.

Every family here is a **named parameter**, swept from a manifest.  None is
IID pixel noise: an error family that perturbs each cell independently is
neither what forecast error looks like nor something a policy can respond to
coherently, so it is not offered as a degradation at all.

Provenance is mandatory (PROTOCOL.md section 7):

``TOY_MECHANISM``
    A mechanism chosen because it is simple and interpretable.
``STRESS_TEST``
    A deliberately adversarial magnitude, not a claim about how often it
    occurs.
``EMPIRICALLY_MOTIVATED``
    Magnitude or shape constrained by a cited observational source.
``LEARNED``
    Fitted from data.

**In this first experiment no family is EMPIRICALLY_MOTIVATED or LEARNED.**
No probability distribution is placed over the error space.  Results are
therefore conditional statements -- "under this error regime, ..." -- and the
report says so rather than inventing likelihoods.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROVENANCE_CLASSES = (
    "TOY_MECHANISM",
    "STRESS_TEST",
    "EMPIRICALLY_MOTIVATED",
    "LEARNED",
)

#: One entry per error family, for the method report and the manifest.
ERROR_FAMILIES: dict[str, dict[str, str]] = {
    "direction_bias_deg": {
        "provenance": "STRESS_TEST",
        "mechanism": "Coherent rotation of the predicted spread pattern about "
        "the reference point. In Mode A the truth field is rotated; in Mode B "
        "the planner's own heading estimate is rotated before it propagates.",
        "why": "A systematic directional error is the error a protective "
        "action is most sensitive to: it moves the predicted threat onto the "
        "wrong houses and the wrong roads.",
    },
    "latency_min": {
        "provenance": "TOY_MECHANISM",
        "mechanism": "The forecast issued from D_s becomes usable only at "
        "s + latency. Until then the policy has no forecast at all.",
        "why": "Timeliness is the other half of the research question. "
        "Modelled as pure delay with no other change, so its effect is not "
        "confounded with accuracy.",
    },
    "rate_bias_factor": {
        "provenance": "STRESS_TEST",
        "mechanism": "Multiplies the predicted time-since-reference, so the "
        "predicted front runs persistently fast (<1) or slow (>1).",
        "why": "Second axis, added after the two-dimensional experiment is "
        "stable (PROTOCOL.md section 13).",
    },
    "displacement_m": {
        "provenance": "STRESS_TEST",
        "mechanism": "Coherent translation of the whole predicted pattern.",
        "why": "Separates 'the shape is right, the place is wrong' from "
        "'the direction is wrong'.",
    },
    "missed_spotting": {
        "provenance": "TOY_MECHANISM",
        "mechanism": "Spot-ignited area is removed from the prediction, so "
        "downwind ignitions the truth contains are absent from the forecast.",
        "why": "A named blind spot rather than an error magnitude. Mode B has "
        "this blind spot structurally, with no parameter set.",
    },
}


@dataclass(frozen=True)
class DegradationSpec:
    """One point in the controlled error space ``theta``.

    Defaults are the undegraded point.  Every field is reported in the
    exported record, so a row can always be traced to its regime.
    """

    direction_bias_deg: float = 0.0
    latency_min: float = 0.0
    rate_bias_factor: float = 1.0
    displacement_m: float = 0.0
    displacement_bearing_deg: float = 0.0
    missed_spotting: bool = False
    #: Free-form label used in figures and tables, e.g. ``"e20_d15"``.
    label: str = "e0_d0"

    def provenance(self) -> tuple[str, ...]:
        """Provenance classes of the families actually switched on here."""
        active: list[str] = []
        if self.direction_bias_deg:
            active.append("direction_bias_deg:STRESS_TEST")
        if self.latency_min:
            active.append("latency_min:TOY_MECHANISM")
        if self.rate_bias_factor != 1.0:
            active.append("rate_bias_factor:STRESS_TEST")
        if self.displacement_m:
            active.append("displacement_m:STRESS_TEST")
        if self.missed_spotting:
            active.append("missed_spotting:TOY_MECHANISM")
        return tuple(active) or ("undegraded",)

    def as_record(self) -> dict:
        return {
            "error_regime": self.label,
            "direction_bias_deg": float(self.direction_bias_deg),
            "latency_min": float(self.latency_min),
            "rate_bias_factor": float(self.rate_bias_factor),
            "displacement_m": float(self.displacement_m),
            "missed_spotting": bool(self.missed_spotting),
        }


@dataclass(frozen=True)
class ErrorGrid:
    """The declared experimental grid over ``theta``.

    The minimum viable experiment is two-dimensional: direction error crossed
    with latency.  Values are chosen for this laboratory's timescale (a 240
    min horizon, a 15 min sensor cadence, missions of order 30 min), not copied
    from an operational setting.
    """

    direction_bias_deg: tuple[float, ...] = (0.0, 10.0, 20.0, 35.0, 55.0)
    latency_min: tuple[float, ...] = (0.0, 5.0, 15.0, 30.0, 60.0)
    extra: tuple[DegradationSpec, ...] = field(default_factory=tuple)

    def points(self) -> list[DegradationSpec]:
        out = [
            DegradationSpec(
                direction_bias_deg=e,
                latency_min=d,
                label=f"e{int(e)}_d{int(d)}",
            )
            for e in self.direction_bias_deg
            for d in self.latency_min
        ]
        out.extend(self.extra)
        return out

    def as_record(self) -> dict:
        return {
            "direction_bias_deg": list(self.direction_bias_deg),
            "latency_min": list(self.latency_min),
            "n_conditions": len(self.points()),
            "extra_conditions": [s.label for s in self.extra],
        }
