"""Policies.  One strong baseline, one primary forecast-aware policy.

Both run through the *same* decision loop (``policy.base.run_policy``), so the
comparison isolates the belief that drives the decision and nothing else: the
cadence, the mission semantics, the commitment rule and the evaluation are
shared code, not two parallel implementations that happen to agree.
"""

from .base import DecisionTrace, PolicyResult, run_policy
from .baseline import BaselinePolicy, FixedBufferPolicy, FireBlindPolicy
from .forecast_aware import ForecastAwarePolicy
from .oracle import OracleReference

__all__ = [
    "DecisionTrace",
    "PolicyResult",
    "run_policy",
    "BaselinePolicy",
    "FixedBufferPolicy",
    "FireBlindPolicy",
    "ForecastAwarePolicy",
    "OracleReference",
]
