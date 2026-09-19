"""Explicit missingness models (``docs/OBSERVATION_MODEL.md#4``).

Four modes, selected per scenario:

``none``               nothing is dropped.
``mcar``               each record dropped independently with ``p_missing``.
``correlated_outage``  a two-state Markov chain per entity on a fixed tick;
                       every record inside a ``down`` run is dropped.
``fire_correlated``    the entity fails with hazard ``lambda_fire_per_min``
                       once the fire is within ``fail_radius_m`` of it, and
                       stays down for ``down_duration_min``.

``fire_correlated`` is **informative missingness**: absence is correlated with
the hidden state.  It is not leakage -- no truth value reaches a planner-facing
file -- but it is an exploitable channel and is flagged in
``docs/FAILURE_MODES.md#F-05``.

All randomness comes from the ``missingness_seed`` stream, in a sub-stream per
entity, so the missingness pattern can be varied while holding measurement
noise fixed.  Draw counts depend only on the configuration and never on the
fire, which keeps prefix causality intact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import MissingnessConfig
from ..rng import SeedRegistry


@dataclass(frozen=True)
class DownInterval:
    """A closed-open interval during which an entity produced nothing."""

    entity_id: str
    start_min: float
    end_min: float
    cause: str

    def as_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "start_min": float(self.start_min),
            "end_min": float(self.end_min),
            "cause": self.cause,
        }


class AvailabilityModel:
    """Decides which records are lost, and records why (into hidden truth)."""

    def __init__(
        self,
        cfg: MissingnessConfig,
        seeds: SeedRegistry,
        horizon_min: float,
        fire_exposure_time: "callable | None" = None,
    ) -> None:
        """
        Args:
            cfg: missingness configuration.
            seeds: the world's seed registry.
            horizon_min: simulation horizon.
            fire_exposure_time: callable ``entity_id -> float`` giving the first
                minute at which the fire came within ``fail_radius_m`` of that
                entity (``inf`` if never).  Required for ``fire_correlated``.
        """
        self.cfg = cfg
        self.seeds = seeds
        self.horizon_min = float(horizon_min)
        self.fire_exposure_time = fire_exposure_time
        self.down_intervals: list[DownInterval] = []

    # -- public ----------------------------------------------------------
    def dropped(self, entity_id: str, times_min: np.ndarray) -> np.ndarray:
        """Boolean mask, ``True`` where the record at that time is lost."""
        times = np.asarray(times_min, dtype=float)
        if times.size == 0 or self.cfg.mode == "none":
            return np.zeros(times.shape, dtype=bool)
        rng = self.seeds.generator("missingness_seed", entity_id)
        if self.cfg.mode == "mcar":
            return self._mcar(entity_id, times, rng)
        if self.cfg.mode == "correlated_outage":
            return self._outage(entity_id, times, rng)
        if self.cfg.mode == "fire_correlated":
            return self._fire_correlated(entity_id, times, rng)
        raise ValueError(f"unhandled missingness mode {self.cfg.mode!r}")  # pragma: no cover

    # -- modes -----------------------------------------------------------
    def _mcar(self, entity_id: str, times: np.ndarray, rng) -> np.ndarray:
        mask = rng.random(times.size) < float(self.cfg.p_missing)
        for t in times[mask]:
            self.down_intervals.append(
                DownInterval(entity_id, float(t), float(t), "mcar")
            )
        return mask

    def _tick_grid(self) -> np.ndarray:
        """Tick times covering ``[0, horizon]``.

        The grid stops at the last tick at or before the horizon: a tick beyond
        it would have no observations to affect, and would produce outage
        records running backwards from the horizon.
        """
        n = int(np.floor(self.horizon_min / float(self.cfg.tick_min))) + 1
        return np.arange(n, dtype=float) * float(self.cfg.tick_min)

    def _outage(self, entity_id: str, times: np.ndarray, rng) -> np.ndarray:
        ticks = self._tick_grid()
        # One draw per tick regardless of state: constant random consumption.
        draws = rng.random(ticks.size)
        state_down = np.zeros(ticks.size, dtype=bool)
        down = False
        for k in range(ticks.size):
            if down:
                if draws[k] < float(self.cfg.p_repair):
                    down = False
            else:
                if draws[k] < float(self.cfg.p_fail):
                    down = True
            state_down[k] = down
        self._record_runs(entity_id, ticks, state_down, "correlated_outage")
        return self._mask_from_ticks(times, ticks, state_down)

    def _fire_correlated(self, entity_id: str, times: np.ndarray, rng) -> np.ndarray:
        ticks = self._tick_grid()
        draws = rng.random(ticks.size)  # constant consumption, fire or no fire
        exposure = (
            float(self.fire_exposure_time(entity_id))
            if self.fire_exposure_time is not None
            else float("inf")
        )
        tick = float(self.cfg.tick_min)
        hazard = 1.0 - float(np.exp(-float(self.cfg.lambda_fire_per_min) * tick))
        state_down = np.zeros(ticks.size, dtype=bool)
        down_until = -np.inf
        for k, t in enumerate(ticks):
            if t < down_until:
                state_down[k] = True
                continue
            exposed = t >= exposure
            if exposed and draws[k] < hazard:
                down_until = t + float(self.cfg.down_duration_min)
                state_down[k] = True
        self._record_runs(entity_id, ticks, state_down, "fire_correlated")
        return self._mask_from_ticks(times, ticks, state_down)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _mask_from_ticks(
        times: np.ndarray, ticks: np.ndarray, state_down: np.ndarray
    ) -> np.ndarray:
        idx = np.clip(np.searchsorted(ticks, times, side="right") - 1, 0, ticks.size - 1)
        return state_down[idx]

    def _record_runs(
        self, entity_id: str, ticks: np.ndarray, state_down: np.ndarray, cause: str
    ) -> None:
        k = 0
        n = state_down.size
        while k < n:
            if not state_down[k]:
                k += 1
                continue
            start = k
            while k < n and state_down[k]:
                k += 1
            if k < n:
                end_t = float(ticks[k])
            else:
                # The run reaches the end of the grid: it lasts at least the
                # tick it started in, and at least to the horizon.
                end_t = max(self.horizon_min, float(ticks[start]) + float(self.cfg.tick_min))
            self.down_intervals.append(
                DownInterval(entity_id, float(ticks[start]), end_t, cause)
            )
