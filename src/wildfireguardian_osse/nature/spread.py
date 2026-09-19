"""Front propagation on the raster by fractional edge accumulation.

An explicit, auditable discretisation of the Huygens principle
(``docs/NATURE_MODEL.md#4``).  For every directed edge from an already-ignited
cell to an unburned burnable neighbour, a fraction of the edge is crossed each
step; the neighbour ignites when the accumulated fraction reaches 1, with
sub-step linear interpolation of the arrival time.

Properties this scheme is chosen for:

* it is exactly isotropic in the continuum limit when ``e = 0`` (validation V1);
* a non-burnable cell is an absolute barrier, not a slow one (validation V4);
* the rate on an edge is the mean of both endpoints' rates, so a fire slows as
  it enters poorer fuel;
* once ignited a cell is a permanent source, so the front cannot
  self-extinguish for numerical reasons (``docs/DECISIONS.md#d-010``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .ros import RosField

#: 8-connected neighbourhood as ``(di, dj)`` offsets, with ``i`` -> north
#: (``y``) and ``j`` -> east (``x``).  This is the ``max_offset = 1`` stencil.
NEIGHBOURS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1),
)


def build_stencil(max_offset: int) -> tuple[tuple[int, int], ...]:
    """Direction set with offsets up to ``max_offset`` cells.

    Only primitive offsets are kept (``gcd(|di|, |dj|) == 1``), since a
    non-primitive one such as ``(2, 2)`` is just two ``(1, 1)`` steps and adds
    no new direction.  ``max_offset`` of 1, 2 and 3 give 8, 16 and 32
    directions.

    More directions matter because the front is **anisotropic**: an elliptical
    spread with eccentricity ``e`` must be approximated by a staircase of
    stencil moves, and the moves available have very different rates.  See
    ``docs/VALIDATION.md#5`` for the measured accuracy.
    """
    if max_offset < 1:
        raise ValueError("stencil max_offset must be >= 1")
    out: list[tuple[int, int]] = []
    for di in range(-max_offset, max_offset + 1):
        for dj in range(-max_offset, max_offset + 1):
            if di == 0 and dj == 0:
                continue
            if np.gcd(abs(di), abs(dj)) != 1:
                continue
            out.append((di, dj))
    return tuple(out)


def intermediate_offsets(di: int, dj: int) -> tuple[tuple[int, int], ...]:
    """Cells a move of ``(di, dj)`` passes over, excluding both endpoints.

    A multi-cell move must not jump a barrier.  The supercover of the segment
    from the source cell centre to the target cell centre is walked, and every
    cell it touches has to be burnable for the move to be allowed.  This keeps
    a one-cell-wide non-burnable line an absolute barrier for every stencil
    (validation world V4).
    """
    steps = max(abs(di), abs(dj)) * 64
    walk: list[tuple[int, int]] = []
    for k in range(steps + 1):
        f = k / steps
        cell = (int(np.floor(f * di + 0.5)), int(np.floor(f * dj + 0.5)))
        if not walk or walk[-1] != cell:
            walk.append(cell)

    covered: list[tuple[int, int]] = []
    for prev, cell in zip(walk, walk[1:]):
        candidates = [cell]
        if prev[0] != cell[0] and prev[1] != cell[1]:
            # The segment passed exactly through a corner; both cells touching
            # it count as crossed, so that a one-cell barrier cannot be slipped
            # through diagonally.
            candidates += [(prev[0], cell[1]), (cell[0], prev[1])]
        for candidate in candidates:
            if candidate not in ((0, 0), (di, dj)) and candidate not in covered:
                covered.append(candidate)
    return tuple(covered)


def neighbour_geometry(cell_size_m: float, stencil=NEIGHBOURS):
    """Return per-direction ``(cos_theta, sin_theta, edge_length_m)``."""
    out = []
    for di, dj in stencil:
        length = float(np.hypot(di, dj))
        out.append((dj / length, di / length, length * float(cell_size_m)))
    return tuple(out)


def shift_into(source: np.ndarray, di: int, dj: int, fill):
    """Return ``out`` with ``out[i, j] = source[i - di, j - dj]``.

    Cells whose source lies outside the array take ``fill``.  Used to place a
    source cell's value at its neighbour's position so that every edge can be
    processed with whole-array operations.
    """
    ny, nx = source.shape
    out = np.full(source.shape, fill, dtype=source.dtype)
    i0d, i1d = max(di, 0), ny + min(di, 0)
    j0d, j1d = max(dj, 0), nx + min(dj, 0)
    i0s, i1s = max(-di, 0), ny + min(-di, 0)
    j0s, j1s = max(-dj, 0), nx + min(-dj, 0)
    if i1d > i0d and j1d > j0d:
        out[i0d:i1d, j0d:j1d] = source[i0s:i1s, j0s:j1s]
    return out


@dataclass
class SpreadResult:
    """Outcome of a propagation run."""

    arrival_time_min: np.ndarray  # +inf where never burned
    burned_cells_series: np.ndarray
    active_cells_series: np.ndarray
    step_times_min: np.ndarray
    max_courant: float
    boundary_contact: bool
    flank_cells_at_horizon: float
    max_eccentricity: float


def _blocked_moves(burnable: np.ndarray, stencil) -> list[np.ndarray]:
    """Per-direction mask of moves that would jump over a non-burnable cell.

    Indexed at the *target* position, like everything else in the step loop.
    """
    out: list[np.ndarray] = []
    for di, dj in stencil:
        mask = np.zeros(burnable.shape, dtype=bool)
        for ci, cj in intermediate_offsets(di, dj):
            # An intermediate cell of the move sits at the target position
            # shifted back by (di - ci, dj - cj).
            mask |= ~shift_into(burnable, di - ci, dj - cj, True)
        out.append(mask)
    return out


def propagate(
    *,
    arrival_time_min: np.ndarray,
    burnable: np.ndarray,
    ros_at: Callable[[float], RosField],
    cell_size_m: float,
    dt_min: float,
    horizon_min: float,
    residence_time_min: float,
    stencil_max_offset: int = 2,
    step_hook: Callable[[float, np.ndarray], None] | None = None,
) -> SpreadResult:
    """Advance the fire front to ``horizon_min``.

    Args:
        arrival_time_min: array of shape ``(ny, nx)``, ``+inf`` for unburned,
            pre-seeded with the initial ignitions.  **Mutated in place.**
        burnable: boolean mask; ``False`` cells can never ignite.
        ros_at: callable mapping a time in minutes to the :class:`RosField`
            for that instant (this is where wind time-dependence enters).
        cell_size_m: raster cell size.
        dt_min: simulation step.
        horizon_min: end of the simulation window.
        residence_time_min: flaming duration, used only to report the active
            cell count -- it never gates propagation
            (``docs/DECISIONS.md#d-010``).
        stencil_max_offset: 1, 2 or 3, giving 8, 16 or 32 directions.  A purely
            numerical parameter: it changes how well the discretisation
            approximates the model, not the model itself
            (``docs/DECISIONS.md#d-016``).
        step_hook: optional callback ``(t_end_of_step, arrival_time)`` invoked
            after each step.  Used by the spotting process, which may ignite
            additional cells by writing into ``arrival_time_min``.

    Returns:
        A :class:`SpreadResult`.  ``max_courant`` is
        ``max(R) * dt / cell_size``; values above ~0.5 mean the scheme is being
        used outside its accurate regime (``docs/FAILURE_MODES.md#G-05``).
    """
    ny, nx = arrival_time_min.shape
    stencil = build_stencil(stencil_max_offset)
    geometry = neighbour_geometry(cell_size_m, stencil)
    blocked = _blocked_moves(burnable, stencil)
    frac = np.zeros((len(stencil), ny, nx), dtype=float)
    # Minutes of "being alight" already credited to each cell as a spread
    # source.  Without this ledger a cell that ignites part-way through a step
    # silently loses the remainder of that step, and the fire runs ~10% slow
    # at dt = 1 min.
    credited_min = np.zeros((ny, nx), dtype=float)

    min_flank_rate = np.inf
    max_ecc = 0.0
    n_steps = int(round(horizon_min / dt_min))
    burned_series = np.zeros(n_steps + 1, dtype=np.int64)
    active_series = np.zeros(n_steps + 1, dtype=np.int64)
    times = np.arange(n_steps + 1, dtype=float) * dt_min
    max_courant = 0.0

    burned_series[0] = int(np.count_nonzero(arrival_time_min <= 0.0))
    active_series[0] = burned_series[0]

    for step in range(n_steps):
        t = step * dt_min
        t_next = t + dt_min

        source = arrival_time_min <= t
        if np.any(source):
            # Restrict work to a bounding box around the burned set, padded by
            # two cells so that every source's neighbours are inside the box.
            rows = np.flatnonzero(source.any(axis=1))
            cols = np.flatnonzero(source.any(axis=0))
            pad = stencil_max_offset + 1
            i0 = max(int(rows[0]) - pad, 0)
            i1 = min(int(rows[-1]) + pad + 1, ny)
            j0 = max(int(cols[0]) - pad, 0)
            j1 = min(int(cols[-1]) + pad + 1, nx)

            ros = ros_at(t)
            # Flank rate of the most anisotropic burning cell: how far the fire
            # can move sideways.  When this times the horizon spans only a cell
            # or two, the raster cannot carry the flank and the burned area is
            # badly under-predicted (``docs/VALIDATION.md#5``).
            flank = ros.r_head * (1.0 - ros.ecc)
            active_flank = flank[source]
            if active_flank.size:
                min_flank_rate = min(min_flank_rate, float(active_flank.max()))
                max_ecc = max(max_ecc, float(ros.ecc[source].max()))
            sub = (slice(i0, i1), slice(j0, j1))
            arrival_sub = arrival_time_min[sub]
            # Uncredited burning time of each potential source, in minutes.
            # For a long-burning cell this is exactly dt; for one ignited
            # during the previous step it is the full time since its arrival,
            # so no spreading time is ever lost or double-counted.
            alight_min = np.maximum(t_next - arrival_sub, 0.0)
            credit_min = np.maximum(alight_min - credited_min[sub], 0.0)
            credited_min[sub] = alight_min
            unburned = ~np.isfinite(arrival_sub)
            open_target = unburned & burnable[sub]

            new_arrival = np.full(arrival_sub.shape, np.inf)
            for k, (di, dj) in enumerate(stencil):
                cos_t, sin_t, edge_len = geometry[k]
                rate_cell = ros.in_direction(cos_t, sin_t)[sub]
                rate_from_source = shift_into(rate_cell, di, dj, 0.0)
                src_here = shift_into(credit_min, di, dj, 0.0)
                edge_rate = 0.5 * (rate_from_source + rate_cell)
                delta = np.where(
                    open_target & ~blocked[k][sub],
                    src_here * edge_rate / edge_len,
                    0.0,
                )
                if delta.max(initial=0.0) > 0.0:
                    max_courant = max(
                        max_courant, float(edge_rate.max()) * dt_min / cell_size_m
                    )
                before = frac[k][sub]
                after = before + delta
                crossed = (after >= 1.0) & (delta > 0.0)
                if np.any(crossed):
                    share = np.where(crossed, (1.0 - before) / np.where(delta > 0, delta, 1.0), 1.0)
                    candidate = np.where(crossed, t + dt_min * np.clip(share, 0.0, 1.0), np.inf)
                    new_arrival = np.minimum(new_arrival, candidate)
                frac[k][sub] = after

            ignite = np.isfinite(new_arrival)
            if np.any(ignite):
                arrival_sub[ignite] = new_arrival[ignite]
                arrival_time_min[sub] = arrival_sub

        if step_hook is not None:
            step_hook(t_next, arrival_time_min)

        burned = arrival_time_min <= t_next
        burned_series[step + 1] = int(np.count_nonzero(burned))
        active_series[step + 1] = int(
            np.count_nonzero(burned & (arrival_time_min > t_next - residence_time_min))
        )

    burned_final = arrival_time_min <= horizon_min
    boundary_contact = bool(
        burned_final[0, :].any()
        or burned_final[-1, :].any()
        or burned_final[:, 0].any()
        or burned_final[:, -1].any()
    )

    return SpreadResult(
        arrival_time_min=arrival_time_min,
        burned_cells_series=burned_series,
        active_cells_series=active_series,
        step_times_min=times,
        max_courant=float(max_courant),
        boundary_contact=boundary_contact,
        flank_cells_at_horizon=(
            float(min_flank_rate * horizon_min / cell_size_m)
            if np.isfinite(min_flank_rate)
            else float("inf")
        ),
        max_eccentricity=float(max_ecc),
    )
