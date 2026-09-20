"""Code-level enforcement of the truth boundary.

The protocol says the planner may never access the nature seed, future fire
state, future weather, future spotting, the final perimeter, future
observations or any evaluator-only quantity.  Stating that is not enough: this
module makes it a runtime error.

Mechanism: hidden truth is handed around wrapped in :class:`SealedTruth`.
Policy and forecast code runs inside :func:`planner_sandbox`, and inside that
context **every** attribute of the wrapper raises
:class:`TruthAccessViolation`.  Outside it the wrapper is transparent, so the
evaluator keeps full access.

    with planner_sandbox():
        decision = policy.decide(view, forecasts)   # truth is unreachable here
    outcome = evaluate(decision, sealed.arrival_time_min)   # evaluator: fine

The inverse guard, :func:`assert_evaluator_context`, marks functions that are
*allowed* to read truth and must therefore never be reachable from a planner.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

_PLANNER_ACTIVE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "wgosse_planner_active", default=False
)


class TruthAccessViolation(RuntimeError):
    """Raised when planner-side code reaches for hidden truth.

    This is never a warning and never recoverable: an experiment in which it
    fires has already been invalidated.
    """


@contextmanager
def planner_sandbox() -> Iterator[None]:
    """Run a block with hidden truth sealed off."""
    token = _PLANNER_ACTIVE.set(True)
    try:
        yield
    finally:
        _PLANNER_ACTIVE.reset(token)


def in_planner_sandbox() -> bool:
    """Whether the calling code is currently inside a planner sandbox."""
    return bool(_PLANNER_ACTIVE.get())


def assert_evaluator_context(what: str) -> None:
    """Guard a function that legitimately reads hidden truth.

    Args:
        what: what is being accessed, for the error message.

    Raises:
        TruthAccessViolation: if called from inside a planner sandbox.
    """
    if in_planner_sandbox():
        raise TruthAccessViolation(
            f"{what} is evaluator-only and was reached from planner code "
            "(experiments/forecast_value_mve/PROTOCOL.md section 2)"
        )


class SealedTruth:
    """Transparent outside a planner sandbox; a wall inside one."""

    __slots__ = ("_truth", "_label")

    def __init__(self, truth: Any, label: str = "hidden truth") -> None:
        object.__setattr__(self, "_truth", truth)
        object.__setattr__(self, "_label", label)

    def __getattr__(self, name: str) -> Any:
        if _PLANNER_ACTIVE.get():
            raise TruthAccessViolation(
                f"planner code tried to read {self._label}.{name}; hidden truth "
                "is unreachable inside a planner sandbox "
                "(experiments/forecast_value_mve/PROTOCOL.md section 2)"
            )
        return getattr(self._truth, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise TruthAccessViolation("hidden truth is read-only")

    def unwrap(self) -> Any:
        """Return the wrapped object.  Evaluator-only."""
        assert_evaluator_context(self._label)
        return self._truth

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "sealed" if _PLANNER_ACTIVE.get() else "open"
        return f"<SealedTruth {self._label} [{state}]>"
