"""Oracle reference.  **Not an executable operational policy.**

It plans against the hidden arrival-time field.  No real dispatcher could run
it, and no claim in any report may treat its loss as achievable.  It exists to
bound the experiment: if the oracle's loss is close to the baseline's, then no
forecast, however good, has much room to help in these worlds -- and that is
itself a result worth reporting (PROTOCOL.md section 5.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..dispatch import ArrivalTimeHazard, PlaceholderDispatchAdapter
from ..info import InformationSet
from .base import Decision
from .baseline import _village_from_info


@dataclass
class OracleReference:
    """Plans with perfect knowledge of the hidden field.  Reference only."""

    truth_hazard: ArrivalTimeHazard
    lead_min: float = 60.0
    adapter: PlaceholderDispatchAdapter = field(
        default_factory=PlaceholderDispatchAdapter
    )
    policy_id: str = "oracle_reference::NOT_OPERATIONAL::v1"

    def belief_hazard(self, info: InformationSet) -> ArrivalTimeHazard:
        return self.truth_hazard

    def decide(
        self, info: InformationSet, pending: tuple[str, ...], s_min: float
    ) -> list[Decision]:
        village = _village_from_info(info)
        residents = {r.resident_id: r for r in village.residents}
        out: list[Decision] = []
        for rid in pending:
            r = residents[rid]
            arrival = float(
                self.truth_hazard.arrival_at([[r.x_m, r.y_m]])[0]
            )
            if arrival > info.horizon_min:
                out.append(Decision(rid, "NO_ACTION", "NEVER_THREATENED"))
                continue
            if arrival > s_min + self.lead_min:
                out.append(Decision(rid, "NO_ACTION", "NOT_YET_DUE"))
                continue
            outcome = self.adapter.plan_and_evaluate(
                village, self.truth_hazard, rid, s_min, info.horizon_min
            )
            if outcome.feasible:
                out.append(Decision(rid, "ACT_NOW", "ORACLE_THREAT", outcome.plan))
            else:
                out.append(Decision(rid, "NO_ACTION", f"ORACLE_{outcome.reason}"))
        return out
