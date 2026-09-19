"""The hidden nature world.

Synthetic nature model for controlled experiments; not an operational wildfire
forecast model (``docs/NATURE_MODEL.md``).
"""

from .ros import RosCoefficients, RosField, build_ros_field, directional_ros, length_to_breadth
from .spread import NEIGHBOURS, SpreadResult, propagate
from .world import NatureTruth, simulate_nature

__all__ = [
    "RosCoefficients",
    "RosField",
    "build_ros_field",
    "directional_ros",
    "length_to_breadth",
    "NEIGHBOURS",
    "SpreadResult",
    "propagate",
    "NatureTruth",
    "simulate_nature",
]
