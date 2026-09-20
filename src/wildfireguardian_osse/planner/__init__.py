"""The planner side of the pipeline: available data, forecasts, skill.

Nothing in this package may touch hidden truth while a planner is running.
That is enforced by :mod:`.sandbox`, not by convention
(``experiments/forecast_value_mve/PROTOCOL.md`` section 2).
"""

from .sandbox import (
    SealedTruth,
    TruthAccessViolation,
    assert_evaluator_context,
    in_planner_sandbox,
    planner_sandbox,
)
from .view import AvailableData, PlannerView, build_planner_view
from .estimate import FireStateEstimate, WindEstimate, estimate_fire_state, estimate_wind
from .forecast import (
    ERROR_LEVELS,
    ErrorProvenanceClass,
    ErrorRegime,
    Forecast,
    ForecastProvenance,
)
from .controlled import make_controlled_perturbation_forecast
from .independent import make_independent_model_forecast
from .skill import ForecastSkill, score_forecast

__all__ = [
    "SealedTruth",
    "TruthAccessViolation",
    "assert_evaluator_context",
    "in_planner_sandbox",
    "planner_sandbox",
    "AvailableData",
    "PlannerView",
    "build_planner_view",
    "FireStateEstimate",
    "WindEstimate",
    "estimate_fire_state",
    "estimate_wind",
    "ERROR_LEVELS",
    "ErrorProvenanceClass",
    "ErrorRegime",
    "Forecast",
    "ForecastProvenance",
    "make_controlled_perturbation_forecast",
    "make_independent_model_forecast",
    "ForecastSkill",
    "score_forecast",
]
