"""The strong baseline: a tuned trigger/buffer policy.

    current observed fire state
      + a conservative buffer, conditioned on wind and on how stale the
        observation is
      + a declared route/action rule

This is the policy the forecast must beat.  It is **not** made weak on
purpose: its four parameters are tuned by search on the validation split
(``tuning.py``), and the buffer is allowed to grow with observed wind speed and
with the age of the last scan -- which is exactly how a competent dispatcher
compensates for not having a forecast.

Two secondary baselines are provided for context, both deliberately simpler:
:class:`FixedBufferPolicy` (no conditioning) and :class:`FireBlindPolicy`
(dispatch on first detection, shortest route, no hazard avoidance).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import BASELINE_VERSION
from ..dispatch import ArrivalTimeHazard, PlaceholderDispatchAdapter
from ..info import InformationSet
from .base import Decision
from .belief import BELIEF_CELL_SIZE_M, distance_to_detections_m, observed_fire_hazard


@dataclass(frozen=True)
class BufferParams:
    """The tuned parameters of the trigger/buffer policy.

    Attributes:
        b0_m: base buffer, metres.
        b1_m_per_ms_per_min: growth of the buffer per m/s of observed wind per
            minute of staleness.
        b2_min: the lead time added to observed staleness, so the buffer
            anticipates a fixed interval beyond "now".
        route_buffer_frac: the *routing* buffer as a fraction of the trigger
            buffer.  These two must be free to differ.  A trigger buffer wants
            to be generous -- act early -- while a routing buffer that is
            equally generous declares every road near the fire unusable and
            the policy strangles itself: it triggers and then refuses to move.
            Tuning is allowed to pick a routing buffer much smaller than the
            trigger buffer, and it does.
    """

    b0_m: float = 300.0
    b1_m_per_ms_per_min: float = 12.0
    b2_min: float = 15.0
    route_buffer_frac: float = 0.35

    def as_record(self) -> dict:
        return {
            "b0_m": self.b0_m,
            "b1_m_per_ms_per_min": self.b1_m_per_ms_per_min,
            "b2_min": self.b2_min,
            "route_buffer_frac": self.route_buffer_frac,
        }


def _observed_wind_speed_ms(info: InformationSet, window_min: float = 30.0) -> float:
    wx = info.weather_observations
    t = wx.get("event_time_min")
    if t is None or len(t) == 0:
        return 0.0
    t = t.astype(float)
    recent = t >= (float(np.max(t)) - window_min)
    return float(max(0.0, np.mean(wx["wind_speed_ms"].astype(float)[recent])))


def _staleness_min(info: InformationSet) -> float:
    latest = info.latest_scan_event_time_min()
    if latest is None:
        return 0.0
    return max(0.0, float(info.information_time_min) - latest)


@dataclass(frozen=True)
class BaselinePolicy:
    """Tuned trigger/buffer policy.  The primary baseline."""

    params: BufferParams = BufferParams()
    adapter: PlaceholderDispatchAdapter = PlaceholderDispatchAdapter()
    cell_size_m: float = BELIEF_CELL_SIZE_M
    policy_id: str = f"baseline_trigger_buffer::{BASELINE_VERSION}"

    def buffer_m(self, info: InformationSet) -> float:
        """Buffer radius at this information time, metres."""
        u = _observed_wind_speed_ms(info)
        age = _staleness_min(info)
        p = self.params
        return float(p.b0_m + p.b1_m_per_ms_per_min * u * (age + p.b2_min))

    def route_buffer_m(self, info: InformationSet) -> float:
        """Clearance demanded of a road, metres.  See :class:`BufferParams`."""
        return float(self.params.route_buffer_frac * self.buffer_m(info))

    def belief_hazard(self, info: InformationSet) -> ArrivalTimeHazard:
        return observed_fire_hazard(info, self.route_buffer_m(info), self.cell_size_m)

    def decide(
        self, info: InformationSet, pending: tuple[str, ...], s_min: float
    ) -> list[Decision]:
        """Dispatch to any pending resident inside the buffer, if a route exists."""
        out: list[Decision] = []
        if not info.has_fire_evidence():
            return [
                Decision(rid, "NO_ACTION", "NO_FIRE_EVIDENCE") for rid in pending
            ]

        buffer_m = self.buffer_m(info)
        hazard = self.belief_hazard(info)
        dist = distance_to_detections_m(info, self.cell_size_m)
        residents = {r["resident_id"]: r for r in info.village["residents"]}

        for rid in pending:
            r = residents[rid]
            j = int(np.clip(r["x_m"] / self.cell_size_m, 0, dist.shape[1] - 1))
            i = int(np.clip(r["y_m"] / self.cell_size_m, 0, dist.shape[0] - 1))
            if float(dist[i, j]) > buffer_m:
                out.append(Decision(rid, "NO_ACTION", "OUTSIDE_TRIGGER_BUFFER"))
                continue
            outcome = self.adapter.plan_and_evaluate(
                _village_from_info(info), hazard, rid, s_min, info.horizon_min
            )
            if outcome.feasible:
                out.append(
                    Decision(rid, "ACT_NOW", "TRIGGERED_INSIDE_BUFFER", outcome.plan)
                )
            else:
                out.append(Decision(rid, "NO_ACTION", f"BELIEF_{outcome.reason}"))
        return out


@dataclass(frozen=True)
class FixedBufferPolicy(BaselinePolicy):
    """Secondary baseline: one buffer radius, no wind or staleness terms."""

    params: BufferParams = BufferParams(
        b0_m=500.0, b1_m_per_ms_per_min=0.0, b2_min=0.0, route_buffer_frac=0.35
    )
    policy_id: str = "secondary_fixed_buffer::v1"


@dataclass(frozen=True)
class FireBlindPolicy:
    """Secondary baseline: dispatch on first detection, ignore the fire.

    Plans the shortest route with no hazard avoidance at all.  Included so the
    experiment can show what the buffer is actually buying.
    """

    adapter: PlaceholderDispatchAdapter = PlaceholderDispatchAdapter()
    cell_size_m: float = BELIEF_CELL_SIZE_M
    policy_id: str = "secondary_fire_blind::v1"

    def belief_hazard(self, info: InformationSet) -> ArrivalTimeHazard:
        shape = (
            int(np.ceil(float(info.grid_meta["height_m"]) / self.cell_size_m)),
            int(np.ceil(float(info.grid_meta["width_m"]) / self.cell_size_m)),
        )
        return ArrivalTimeHazard(
            arrival_time_min=np.full(shape, np.inf),
            cell_size_m=self.cell_size_m,
            source="FIRE_BLIND",
        )

    def decide(
        self, info: InformationSet, pending: tuple[str, ...], s_min: float
    ) -> list[Decision]:
        if not info.has_fire_evidence():
            return [Decision(rid, "NO_ACTION", "NO_FIRE_EVIDENCE") for rid in pending]
        hazard = self.belief_hazard(info)
        village = _village_from_info(info)
        out: list[Decision] = []
        for rid in pending:
            outcome = self.adapter.plan_and_evaluate(
                village, hazard, rid, s_min, info.horizon_min
            )
            if outcome.feasible:
                out.append(Decision(rid, "ACT_NOW", "FIRST_DETECTION", outcome.plan))
            else:
                out.append(Decision(rid, "NO_ACTION", f"BELIEF_{outcome.reason}"))
        return out


def _village_from_info(info: InformationSet):
    """Rebuild the village object from the planner-visible dictionary.

    Deliberately reconstructed from ``info.village`` rather than taken from the
    world: a policy must be unable to reach anything the information set did
    not carry, including the world object that owns the village.
    """
    from ..village import RoadEdge, Resident, Village

    v = info.village
    nodes = {k: (float(p[0]), float(p[1])) for k, p in v["nodes"].items()}
    edges = []
    for e in v["edges"]:
        a, b = nodes[e["u"]], nodes[e["v"]]
        n = max(2, int(np.ceil(e["length_m"] / 60.0)) + 1)
        ts = np.linspace(0.0, 1.0, n)
        samples = tuple(
            (float(a[0] + t * (b[0] - a[0])), float(a[1] + t * (b[1] - a[1])))
            for t in ts
        )
        edges.append(
            RoadEdge(
                edge_id=e["edge_id"],
                u=e["u"],
                v=e["v"],
                road_class=e["road_class"],
                length_m=float(e["length_m"]),
                sample_xy_m=samples,
            )
        )
    residents = tuple(
        Resident(
            resident_id=r["resident_id"],
            x_m=float(r["x_m"]),
            y_m=float(r["y_m"]),
            node_id=r["node_id"],
            self_evacuation_capable=bool(r["self_evacuation_capable"]),
            pickup_duration_min=float(r["pickup_duration_min"]),
        )
        for r in v["residents"]
    )
    return Village(
        village_id=v["village_id"],
        nodes=nodes,
        edges=tuple(edges),
        residents=residents,
        base_node=v["base_node"],
        destination_nodes=tuple(v["destination_nodes"]),
        centre_xy_m=(float(v["centre_xy_m"][0]), float(v["centre_xy_m"][1])),
    )
