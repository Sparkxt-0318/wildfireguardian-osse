"""Road network, protective missions, and the assisted-dispatch adapter.

Mission *semantics* are owned by ``wildfireguardian-assisted-dispatch``.  This
package declares the adapter contract and ships a clearly-labelled minimal
placeholder until that package is available
(``experiments/forecast_value_mve/PROTOCOL.md`` section 7).
"""

from .outcomes import FailureReason, FeasibilityState, MissionKind, MissionResult
from .network import Edge, RoadNetwork, Route, build_road_network
from .village import WorldGeometry, build_geometry
from .dispatch import DispatchAdapter, PlaceholderDispatchAdapter

__all__ = [
    "FailureReason",
    "FeasibilityState",
    "MissionKind",
    "MissionResult",
    "Edge",
    "RoadNetwork",
    "Route",
    "build_road_network",
    "WorldGeometry",
    "build_geometry",
    "DispatchAdapter",
    "PlaceholderDispatchAdapter",
]
