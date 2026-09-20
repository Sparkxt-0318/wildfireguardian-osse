"""The information set ``D_s`` -- the single gate between the world and a planner.

    HIDDEN WORLD --[ build_information_set(world, s) ]--> D_s --> PLANNER

Every planner and every policy in this package takes an :class:`InformationSet`
and nothing else.  The gate is one short function, deliberately, so that it can
be read in full during an audit.

Three enforcement layers, in decreasing order of strength:

1. **Structure.**  :class:`InformationSet` holds arrays and plain dicts.  It
   holds no reference to the hidden world, so there is no attribute path from a
   planner to truth.  ``tests/fv/test_information_set.py`` walks the whole
   object graph and fails if any laboratory truth object is reachable.
2. **Construction-time assertions.**  The gate re-checks availability, seed
   absence and forbidden field names on every build, and raises.
3. **Execution-time guard.**  :func:`truth_access_guard` makes any attempt to
   read a ``truth/`` artefact from disk raise while a planner is running.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import numpy as np

from wildfireguardian_osse.storage.reader import available_at

#: Column or key names that must never appear in an information set.  A
#: superset of the laboratory's own forbidden list, extended with the
#: experiment layer's evaluator-only quantities.
FORBIDDEN_KEY_SUBSTRINGS: tuple[str, ...] = (
    "arrival_time_min",  # the truth field itself
    "burned_mask",
    "seed",
    "nature_param",
    "true_",
    "_true",
    "spot_event",
    "ignition",
    "detection_ledger",
    "sensor_state",
    "is_spurious",
    "final_perimeter",
)

#: Names that are legitimately present and would otherwise trip the scan.
FORBIDDEN_KEY_ALLOWLIST: tuple[str, ...] = (
    "event_time_min",
    "acquisition_time_min",
    "processing_time_min",
    "availability_time_min",
)


class LeakageError(AssertionError):
    """Raised when hidden truth would reach a planner-facing object."""


@dataclass(frozen=True)
class InformationSet:
    """Everything a planner may legally use at information time ``s``.

    Attributes:
        world_id: identifier only; it is *not* a seed and cannot be inverted to
            one (the seed derivation is a one-way hash of the master seed,
            which the planner never sees).
        information_time_min: ``s``, minutes since ``t0``.
        fire_detections / fire_scan_log / weather_observations: observation
            tables already filtered to ``availability_time_min <= s``.
        static_context: elevation and coarse fuel class, published as static
            context by the laboratory (``docs/DECISIONS.md#d-006``).
        village: planner-visible road, house, base and destination geometry.
        published_specs: nominal sensor specifications, not the realised ones.
        horizon_min: the decision horizon the planner is asked about.  This is
            a property of the *exercise*, not of the hidden fire.
    """

    world_id: int
    information_time_min: float
    fire_detections: Mapping[str, np.ndarray]
    fire_scan_log: Mapping[str, np.ndarray]
    weather_observations: Mapping[str, np.ndarray]
    station_metadata: tuple[dict, ...]
    published_specs: Mapping[str, Any]
    static_context: Mapping[str, np.ndarray]
    village: Mapping[str, Any]
    grid_meta: Mapping[str, Any]
    horizon_min: float
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def n_detections(self) -> int:
        col = self.fire_detections.get("obs_id")
        return 0 if col is None else int(len(col))

    def has_fire_evidence(self) -> bool:
        return self.n_detections() > 0

    def latest_scan_event_time_min(self) -> float | None:
        """Event time of the most recent *available* scan, or ``None``.

        Note the two different times: the planner knows the scan happened at
        ``event_time_min`` but only learned it at ``availability_time_min``.
        Reasoning about fire motion uses the former; legality uses the latter.
        """
        col = self.fire_scan_log.get("event_time_min")
        if col is None or len(col) == 0:
            return None
        return float(np.max(col.astype(float)))


def _iter_keys(node: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(node, Mapping):
        for k, v in node.items():
            here = f"{path}.{k}" if path else str(k)
            yield here, v
            yield from _iter_keys(v, here)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            here = f"{path}[{i}]"
            yield from _iter_keys(v, here)


def _check_forbidden_names(info: InformationSet) -> list[str]:
    problems: list[str] = []
    payloads = {
        "fire_detections": info.fire_detections,
        "fire_scan_log": info.fire_scan_log,
        "weather_observations": info.weather_observations,
        "static_context": info.static_context,
        "village": info.village,
        "published_specs": info.published_specs,
        "grid_meta": info.grid_meta,
        "station_metadata": list(info.station_metadata),
    }
    for where, payload in payloads.items():
        for path, _value in _iter_keys(payload, where):
            leaf = path.rsplit(".", 1)[-1].split("[")[0]
            if leaf in FORBIDDEN_KEY_ALLOWLIST:
                continue
            for bad in FORBIDDEN_KEY_SUBSTRINGS:
                if bad in leaf:
                    problems.append(f"forbidden field name {path!r} (matched {bad!r})")
    return problems


def _check_no_seed_values(info: InformationSet, seed_values: Iterable[int]) -> list[str]:
    values = {int(v) for v in seed_values}
    if not values:
        return []
    problems: list[str] = []
    for where, payload in (
        ("village", info.village),
        ("published_specs", info.published_specs),
        ("grid_meta", info.grid_meta),
        ("provenance", info.provenance),
    ):
        for path, value in _iter_keys(payload, where):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if float(value).is_integer() and int(value) in values:
                    problems.append(f"seed value present at {path!r}")
            elif isinstance(value, str) and any(str(v) in value for v in values):
                problems.append(f"seed value present in string at {path!r}")
    return problems


def _check_availability(info: InformationSet) -> list[str]:
    problems: list[str] = []
    s = float(info.information_time_min)
    for name, table in (
        ("fire_detections", info.fire_detections),
        ("fire_scan_log", info.fire_scan_log),
        ("weather_observations", info.weather_observations),
    ):
        col = table.get("availability_time_min")
        if col is None:
            problems.append(f"{name} has no availability_time_min column")
            continue
        if len(col) and float(np.max(col.astype(float))) > s + 1e-9:
            problems.append(
                f"{name} contains a record available after s={s}: "
                f"max availability {float(np.max(col.astype(float)))}"
            )
    return problems


def audit_information_set(
    info: InformationSet, seed_values: Iterable[int] = ()
) -> list[str]:
    """Return every leakage problem found in ``info``.  Empty means clean."""
    return (
        _check_availability(info)
        + _check_forbidden_names(info)
        + _check_no_seed_values(info, seed_values)
    )


def build_information_set(world, information_time_min: float) -> InformationSet:
    """The gate.  Build ``D_s`` for one world at one information time.

    Args:
        world: a :class:`~wildfireguardian_fv.world.ExperimentWorld`.  Typed
            loosely on purpose -- this module must not import the module that
            holds hidden truth, so that the import graph itself shows the
            direction of the dependency.
        information_time_min: ``s``.

    Returns:
        A frozen :class:`InformationSet` holding **only** observations whose
        ``availability_time_min <= s``, static context, published specs and
        village geometry.

    Raises:
        LeakageError: if the constructed set fails any audit check.  Failing
            loudly is the contract (PROTOCOL.md section 12).
        ValueError: if ``information_time_min`` is negative.

    Note:
        A record acquired earlier but processed later is unavailable until its
        availability time.  That filter is
        :func:`wildfireguardian_osse.storage.reader.available_at`, reused here
        rather than re-implemented, so the experiment cannot drift from the
        laboratory's own definition of legality.
    """
    s = float(information_time_min)
    if s < 0.0:
        raise ValueError(f"information time must be >= 0, got {s}")

    obs = world.observations
    info = InformationSet(
        world_id=int(world.world_id),
        information_time_min=s,
        fire_detections=available_at(dict(obs.fire_detections.columns), s),
        fire_scan_log=available_at(dict(obs.fire_scan_log.columns), s),
        weather_observations=available_at(
            dict(obs.weather_observations.columns), s
        ),
        station_metadata=tuple(obs.station_metadata),
        published_specs=dict(obs.published_specs),
        static_context=dict(world.static_context),
        village=world.village.as_planner_dict(),
        grid_meta=dict(world.grid_meta),
        horizon_min=float(world.horizon_min),
    )

    problems = audit_information_set(info, world.all_hidden_seed_values())
    if problems:
        raise LeakageError(
            "information set failed its leakage audit:\n  - " + "\n  - ".join(problems)
        )
    return info


@contextlib.contextmanager
def truth_access_guard():
    """Make any read of a laboratory ``truth/`` artefact raise while running.

    Wraps every planner and policy call in the runner.  It is a backstop, not
    the primary defence -- the primary defence is that an
    :class:`InformationSet` has no path to truth at all -- but it catches the
    one thing structure cannot: a planner that opens the world directory.
    """
    real_load = np.load
    real_open = open

    def guarded_load(file, *args, **kwargs):
        if "truth" in str(file).replace("\\", "/").split("/"):
            raise LeakageError(
                f"planner-side code attempted to read hidden truth: {file!r}"
            )
        return real_load(file, *args, **kwargs)

    def guarded_open(file, *args, **kwargs):  # pragma: no cover - exercised by test
        if "truth" in str(file).replace("\\", "/").split("/"):
            raise LeakageError(
                f"planner-side code attempted to read hidden truth: {file!r}"
            )
        return real_open(file, *args, **kwargs)

    import builtins

    np.load = guarded_load  # type: ignore[assignment]
    builtins.open = guarded_open  # type: ignore[assignment]
    try:
        yield
    finally:
        np.load = real_load  # type: ignore[assignment]
        builtins.open = real_open  # type: ignore[assignment]
