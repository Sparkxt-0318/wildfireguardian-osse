"""Forecast-value experiment layer built *on top of* the OSSE laboratory.

    NATURE WORLD -> OBSERVATION PROCESS -> AVAILABLE DATA D_s
                 -> PLANNER / FORECAST  -> POLICY -> ACTION / MISSION
                 -> HIDDEN-WORLD EVALUATION

This is a **separate top-level package** on purpose.  ``docs/SCOPE.md`` says the
laboratory must be usable by any evaluation method, so the laboratory must not
know that this experiment exists.  The dependency direction is one-way::

    wildfireguardian_fv  ---->  wildfireguardian_osse        (allowed)
    wildfireguardian_osse ---->  wildfireguardian_fv         (forbidden)

``tests/fv/test_package_separation.py`` enforces that mechanically.  See
``docs/DECISIONS.md#d-017``.

Nothing in this package may read hidden truth on the planner's behalf.  The
single gate is :func:`wildfireguardian_fv.info.build_information_set`; see
``experiments/forecast_value_mve/reports/LEAKAGE_AUDIT.md``.
"""

from __future__ import annotations

#: Version of the experiment layer as a whole.  Bump on any behaviour change.
FV_VERSION = "0.1.0"

#: Component versions recorded in every experiment manifest
#: (``experiments/forecast_value_mve/PROTOCOL.md`` section 9).
WORLD_GENERATOR_VERSION = "fv-worlds-v1"
PLANNER_MODEL_VERSION = "fv-planner-v1"
DEGRADATION_MODEL_VERSION = "fv-degradation-v1"
BASELINE_VERSION = "fv-baseline-trigger-buffer-v1"
POLICY_VERSION = "fv-forecast-aware-v1"
LOSS_VERSION = "fv-loss-v1"
DISPATCH_ADAPTER_VERSION = "fv-internal-placeholder-v1"

#: Printed next to every figure and table produced from this package.
RESULT_BANNER = (
    "SYNTHETIC OSSE RESULT -- generic synthetic worlds, not Korean-anchored. "
    "Statements apply to the declared nature and observation models only."
)

__all__ = [
    "FV_VERSION",
    "WORLD_GENERATOR_VERSION",
    "PLANNER_MODEL_VERSION",
    "DEGRADATION_MODEL_VERSION",
    "BASELINE_VERSION",
    "POLICY_VERSION",
    "LOSS_VERSION",
    "DISPATCH_ADAPTER_VERSION",
    "RESULT_BANNER",
]
