"""Validation: leakage scanning, world checks, analytic metrics, batch summary."""

from .leakage import FORBIDDEN_KEY_FRAGMENTS, scan_world_for_leakage
from .checks import check_time_semantics, validate_world
from .analytic import (
    burned_centroid,
    directional_extent,
    effective_speed_ratio,
    principal_axis_deg,
)
from .summary import summarize_batch, summary_markdown

__all__ = [
    "FORBIDDEN_KEY_FRAGMENTS",
    "scan_world_for_leakage",
    "check_time_semantics",
    "validate_world",
    "burned_centroid",
    "directional_extent",
    "effective_speed_ratio",
    "principal_axis_deg",
    "summarize_batch",
    "summary_markdown",
]
