"""Forecast generation.  Two modes, deliberately different in kind.

``independent``  -- ``INDEPENDENT_MODEL_FORECAST``, Mode B.  A structurally
    different simplified prediction model that consumes only ``D_s``.  Its
    errors are *emergent*: nobody chose them.
``perturbation`` -- ``CONTROLLED_PERTURBATION``, Mode A.  The evaluator builds
    a forecast by degrading hidden truth in a named way, to isolate the causal
    effect of one error family.

Mode A is not leakage-safe and is not meant to be; it is a mechanism probe.
Flagship conclusions rest on Mode B (LEAKAGE_AUDIT.md section 4).
"""

from .independent import IndependentPlanner, PlannerCoefficients
from .perturbation import ControlledPerturbationForecaster

__all__ = [
    "IndependentPlanner",
    "PlannerCoefficients",
    "ControlledPerturbationForecaster",
]
