"""Figures for the forecast-value MVE.

Every figure carries the same footer: these are synthetic OSSE worlds, not
Korean-anchored, and the numbers are conditional on the declared loss and error
regimes.  A figure that travels without that caption is a figure that will be
misread.

Colour follows the job, not taste:

* ``Delta J`` has a meaningful zero and a sign, so it is **diverging**
  (blue <-> red with a neutral grey midpoint).
* Latency is an **ordered magnitude**, so it is a single-hue **ordinal** ramp.
* Forecast mode and policy are **identity**, so they take categorical slots in
  fixed order, capped at three for the scatter (the all-pairs CVD gate).

All palettes were checked with the data-viz validator before use; the three
slots below clear the all-pairs floors, and the sub-3:1 contrast warning is
relieved the documented way -- visible direct labels and a table view (the
annotated heatmap cells, and the CSV records themselves).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
import numpy as np  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8985"
GRID = "#e6e5e1"

#: Categorical slots 1-3 (validated all-pairs, light mode).
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
#: Ordinal blue ramp, steps 250-650 (validated --ordinal, light mode).
ORDINAL = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")
#: Categorical slots 1-5 for composition.
COMPOSITION = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")
#: Diverging pair with a neutral grey midpoint.
DIVERGING = LinearSegmentedColormap.from_list(
    "wg_diverging", ["#184f95", "#86b6ef", "#f0efec", "#f0a3a3", "#b02828"]
)

FOOTER = (
    "Synthetic OSSE worlds — NOT Korean-anchored. Conditional on the declared "
    "loss (mve-loss-1.1.0) and error regimes; no probability is assigned to "
    "regimes. See experiments/forecast_value_mve/PROTOCOL.md."
)

FROZEN_POLICY = "forecast_aware_feasibility"
AGGRESSIVE_POLICY = "forecast_aware_margin_0"
ERROR_ORDER = ("none", "low", "medium", "high", "severe")


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)


def _finish(fig, path: Path, title: str, subtitle: str, note: str | None = None) -> Path:
    """Title, subtitle and footer placed *outside* the axes box.

    ``bbox_inches="tight"`` expands the saved area to include artists beyond
    the figure rectangle, so stacking them above y=1 keeps them clear of the
    axes instead of landing on top of each other.
    """
    fig.patch.set_facecolor(SURFACE)
    height = fig.get_size_inches()[1]
    line = 0.30 / height          # ~0.30 inch per header line, in figure units
    fig.text(0.0, 1.0 + 1.55 * line, title, ha="left", va="bottom",
             fontsize=14, color=INK, weight="bold")
    fig.text(0.0, 1.0 + 0.45 * line, subtitle, ha="left", va="bottom",
             fontsize=9.5, color=INK_SECONDARY)
    if note:
        fig.text(0.0, -0.75 * line, note, ha="left", va="top",
                 fontsize=8, color=INK_SECONDARY)
    fig.text(0.0, (-1.65 if note else -1.0) * line, FOOTER, ha="left", va="top",
             fontsize=7.5, color=INK_MUTED)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=SURFACE, bbox_inches="tight",
                pad_inches=0.28)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# aggregation helpers
# ---------------------------------------------------------------------------

def _baseline_loss(rows, mission_kind: str) -> dict[int, float]:
    return {
        int(r["world_id"]): float(r["loss"])
        for r in rows
        if r["policy_id"] == "baseline_tuned_buffer" and r["mission_kind"] == mission_kind
    }


def cell(rows, *, mission_kind, mode, regime, latency, policy_id):
    """Paired mean ``Delta J``, its standard error, mean CSI and the count."""
    baseline = _baseline_loss(rows, mission_kind)
    deltas, skills = [], []
    for r in rows:
        if (
            r["policy_id"] != policy_id
            or r["mission_kind"] != mission_kind
            or r["forecast_mode"] != mode
            or r["error_regime"] != regime
            or r.get("wait_semantics", "ACT_NOW") != "ACT_NOW"
            or not np.isclose(float(r["latency_min"]), float(latency))
        ):
            continue
        world = int(r["world_id"])
        if world not in baseline:
            continue
        deltas.append(float(r["loss"]) - baseline[world])
        skill = float(r["skill_csi"])
        if np.isfinite(skill):
            skills.append(skill)
    if not deltas:
        return None
    arr = np.asarray(deltas)
    se = float(arr.std(ddof=1) / np.sqrt(arr.size)) if arr.size > 1 else float("nan")
    return {
        "mean_delta_j": float(arr.mean()),
        "se": se,
        "resolved": bool(arr.size > 1 and np.isfinite(se) and abs(arr.mean()) > 2 * se),
        "mean_csi": float(np.mean(skills)) if skills else float("nan"),
        "n": int(arr.size),
    }


# ---------------------------------------------------------------------------
# Figure 1 -- forecast skill vs decision value
# ---------------------------------------------------------------------------

def figure_skill_vs_value(rows, out_dir: Path, mission_kind="self_evacuation") -> Path:
    fig, ax = plt.subplots(figsize=(8.2, 5.4))
    _style(ax)
    series = (
        ("Controlled perturbation · tuned policy", "CONTROLLED_PERTURBATION",
         FROZEN_POLICY, ERROR_ORDER, SERIES[0], "o"),
        ("Controlled perturbation · aggressive probe", "CONTROLLED_PERTURBATION",
         AGGRESSIVE_POLICY, ERROR_ORDER, SERIES[1], "s"),
        ("Independent model · tuned policy", "INDEPENDENT_MODEL_FORECAST",
         FROZEN_POLICY, ("independent_model",), SERIES[2], "^"),
    )
    latencies = (0.0, 5.0, 15.0, 30.0, 60.0)
    for label, mode, policy_id, regimes, colour, marker in series:
        xs, ys = [], []
        for regime in regimes:
            for latency in latencies:
                point = cell(rows, mission_kind=mission_kind, mode=mode,
                             regime=regime, latency=latency, policy_id=policy_id)
                if point and np.isfinite(point["mean_csi"]):
                    xs.append(point["mean_csi"])
                    ys.append(point["mean_delta_j"])
        ax.scatter(xs, ys, s=78, c=colour, marker=marker, label=label,
                   edgecolors=SURFACE, linewidths=2.0, zorder=3)

    ax.axhline(0.0, color=INK_SECONDARY, linewidth=1.5, zorder=2)
    ax.text(0.995, 0.002, "baseline", transform=ax.get_yaxis_transform(),
            ha="right", va="bottom", fontsize=8.5, color=INK_SECONDARY)
    ax.set_xlabel("forecast skill  (CSI over the forecast's valid window)",
                  fontsize=10, color=INK_SECONDARY)
    ax.set_ylabel("Δ J   (forecast-aware − tuned baseline)", fontsize=10, color=INK_SECONDARY)
    ax.annotate("better than baseline", xy=(0.02, 0.06), xycoords="axes fraction",
                fontsize=9, color=INK_SECONDARY)
    ax.annotate("worse than baseline", xy=(0.02, 0.93), xycoords="axes fraction",
                fontsize=9, color=INK_SECONDARY)
    legend = ax.legend(frameon=False, fontsize=9, loc="upper right")
    for text in legend.get_texts():
        text.set_color(INK)
    return _finish(
        fig, out_dir / "fig1_skill_vs_value.png",
        "Figure 1 · Conventional forecast skill does not determine decision value",
        f"{mission_kind.replace('_', ' ')} · each point is one (error regime, latency) "
        "condition, averaged over the paired worlds",
    )


# ---------------------------------------------------------------------------
# Figure 2 -- error x latency heatmap
# ---------------------------------------------------------------------------

def figure_delta_heatmap(rows, out_dir: Path, mission_kind="self_evacuation") -> Path:
    latencies = (0.0, 5.0, 15.0, 30.0, 60.0)
    policies = ((FROZEN_POLICY, "tuned policy (safety margin 90 min)"),
                (AGGRESSIVE_POLICY, "aggressive probe (margin 0)"))
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.6))
    grids = []
    for policy_id, _ in policies:
        grid = np.full((len(ERROR_ORDER), len(latencies)), np.nan)
        for i, regime in enumerate(ERROR_ORDER):
            for j, latency in enumerate(latencies):
                point = cell(rows, mission_kind=mission_kind,
                             mode="CONTROLLED_PERTURBATION", regime=regime,
                             latency=latency, policy_id=policy_id)
                if point:
                    grid[i, j] = point["mean_delta_j"]
        grids.append(grid)

    limit = float(np.nanmax(np.abs(np.concatenate([g.ravel() for g in grids]))))
    limit = max(limit, 1e-6)
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)

    for ax, grid, (_, label) in zip(axes, grids, policies):
        ax.set_facecolor(SURFACE)
        image = ax.imshow(grid, cmap=DIVERGING, norm=norm, aspect="auto")
        ax.set_xticks(range(len(latencies)), [f"{int(v)}" for v in latencies])
        ax.set_yticks(range(len(ERROR_ORDER)), ERROR_ORDER)
        ax.set_xlabel("forecast latency (min)", fontsize=10, color=INK_SECONDARY)
        ax.set_title(label, fontsize=10, color=INK, pad=8)
        ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
        for side in ax.spines.values():
            side.set_visible(False)
        # Annotated cells are the table-view relief the palette check requires.
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                if np.isnan(grid[i, j]):
                    continue
                shade = abs(grid[i, j]) / limit
                ax.text(j, i, f"{grid[i, j]:+.2f}", ha="center", va="center",
                        fontsize=8.5, color="#ffffff" if shade > 0.55 else INK)
        # 2px surface gaps between cells
        ax.set_xticks(np.arange(-0.5, len(latencies), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(ERROR_ORDER), 1), minor=True)
        ax.grid(which="minor", color=SURFACE, linewidth=2.0)
        ax.tick_params(which="minor", length=0)

    axes[0].set_ylabel("error regime", fontsize=10, color=INK_SECONDARY)
    bar = fig.colorbar(image, ax=axes, fraction=0.035, pad=0.02)
    bar.set_label("Δ J   (negative = forecast-aware better)", fontsize=9, color=INK_SECONDARY)
    bar.ax.tick_params(colors=INK_SECONDARY, labelsize=8.5, length=0)
    bar.outline.set_visible(False)
    return _finish(
        fig, out_dir / "fig2_error_latency_heatmap.png",
        "Figure 2 · Δ J across the error × latency grid",
        f"{mission_kind.replace('_', ' ')} · controlled perturbation · paired within worlds",
    )


# ---------------------------------------------------------------------------
# Figure 3 -- break-even frontier
# ---------------------------------------------------------------------------

def figure_frontier(rows, out_dir: Path, mission_kind="self_evacuation") -> Path:
    latencies = (0.0, 5.0, 15.0, 30.0, 60.0)
    policies = ((FROZEN_POLICY, "tuned policy (margin 90 min)"),
                (AGGRESSIVE_POLICY, "aggressive probe (margin 0)"))
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 5.0), sharey=True)

    for ax, (policy_id, label) in zip(axes, policies):
        _style(ax)
        x = np.arange(len(ERROR_ORDER))
        bands: set[int] = set()
        for k, latency in enumerate(latencies):
            means, resolved = [], []
            for regime in ERROR_ORDER:
                point = cell(rows, mission_kind=mission_kind,
                             mode="CONTROLLED_PERTURBATION", regime=regime,
                             latency=latency, policy_id=policy_id)
                means.append(point["mean_delta_j"] if point else np.nan)
                resolved.append(bool(point and point["resolved"]))
            ax.plot(x, means, color=ORDINAL[k], linewidth=2.0,
                    label=f"{int(latency)} min", zorder=3)
            solid = [m if r else np.nan for m, r in zip(means, resolved)]
            hollow = [m if not r else np.nan for m, r in zip(means, resolved)]
            ax.scatter(x, solid, s=64, color=ORDINAL[k], edgecolors=SURFACE,
                       linewidths=2.0, zorder=4)
            ax.scatter(x, hollow, s=64, facecolors=SURFACE, edgecolors=ORDINAL[k],
                       linewidths=2.0, zorder=4)
            # every sign change between resolved levels is recorded; the bands
            # are drawn after autoscaling so their labels sit inside the axes
            for i in range(len(x) - 1):
                if resolved[i] and resolved[i + 1] and np.sign(means[i]) != np.sign(means[i + 1]):
                    bands.add(i)
        ax.axhline(0.0, color=INK_SECONDARY, linewidth=1.5, zorder=2)
        top = ax.get_ylim()[1]
        for i in sorted(bands):
            ax.axvspan(i, i + 1, color="#e0dfda", alpha=0.85, zorder=0)
            ax.text(i + 0.5, top, " break-even ", ha="center", va="top",
                    fontsize=8, color=INK_SECONDARY,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor=SURFACE,
                              edgecolor="none"))
        ax.set_xticks(x, ERROR_ORDER)
        ax.set_xlabel("error regime", fontsize=10, color=INK_SECONDARY)
        ax.set_title(label, fontsize=10, color=INK, pad=8)

    axes[0].set_ylabel("Δ J   (forecast-aware − tuned baseline)", fontsize=10,
                       color=INK_SECONDARY)
    legend = axes[1].legend(frameon=False, fontsize=9, title="latency",
                            loc="upper left")
    legend.get_title().set_color(INK_SECONDARY)
    legend.get_title().set_fontsize(9)
    for text in legend.get_texts():
        text.set_color(INK)
    return _finish(
        fig, out_dir / "fig3_break_even_frontier.png",
        "Figure 3 · Break-even frontier, with every crossing marked",
        f"{mission_kind.replace('_', ' ')} · a frontier exists for the aggressive "
        "probe and not for the tuned policy",
        note=(
            "Filled markers are separable from Monte-Carlo noise (|mean| > 2 SE); "
            "hollow markers are UNRESOLVED. Shaded bands bracket a sign change "
            "between two resolved levels — nothing is interpolated inside them."
        ),
    )


# ---------------------------------------------------------------------------
# Figure 4 -- failure-reason composition
# ---------------------------------------------------------------------------

def figure_failure_reasons(rows, out_dir: Path, mission_kind="self_evacuation") -> Path:
    groups = [
        ("tuned\nbaseline", lambda r: r["policy_id"] == "baseline_tuned_buffer"),
        ("fixed\nbuffer", lambda r: r["policy_id"] == "baseline_fixed_buffer"),
        ("fire-blind", lambda r: r["policy_id"] == "baseline_fire_blind"),
        ("forecast-aware\n(tuned)", lambda r: r["policy_id"] == FROZEN_POLICY
         and r["error_regime"] == "none" and float(r["latency_min"]) == 0.0),
        ("forecast-aware\n(severe error)", lambda r: r["policy_id"] == FROZEN_POLICY
         and r["error_regime"] == "severe" and float(r["latency_min"]) == 0.0),
        ("aggressive probe\n(severe error)", lambda r: r["policy_id"] == AGGRESSIVE_POLICY
         and r["error_regime"] == "severe" and float(r["latency_min"]) == 0.0),
    ]
    # The category list must cover what actually happens, or the residual
    # "other" bucket hides the dominant failure mode -- as it did in the first
    # version of this figure, where route_already_burned was missing.
    reasons = ["none", "route_already_burned", "route_cut_en_route",
               "village_burned_before_pickup", "not_ordered", "horizon_exceeded"]
    pretty = {"none": "mission completed",
              "route_already_burned": "route already blocked at departure",
              "route_cut_en_route": "route cut en route",
              "village_burned_before_pickup": "village reached before pickup",
              "not_ordered": "never ordered (and threatened)",
              "horizon_exceeded": "horizon exceeded"}

    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    _style(ax)
    labels, stacks = [], []
    for label, predicate in groups:
        selected = [r for r in rows
                    if r["mission_kind"] == mission_kind and predicate(r)
                    and r.get("wait_semantics", "ACT_NOW") == "ACT_NOW"]
        if not selected:
            continue
        counts = []
        for reason in reasons:
            counts.append(sum(1 for r in selected if str(r["failure_reason"]) == reason))
        other = len(selected) - sum(counts)
        total = max(len(selected), 1)
        stacks.append([100.0 * c / total for c in counts] + [100.0 * other / total])
        labels.append(label)

    bottoms = np.zeros(len(labels))
    palette = list(COMPOSITION) + [COMPOSITION[0], INK_MUTED]
    for k, reason in enumerate(reasons + ["other"]):
        values = np.array([s[k] for s in stacks])
        if not np.any(values > 0):
            continue
        ax.bar(labels, values, bottom=bottoms, color=palette[k], width=0.66,
               label=pretty.get(reason, reason), edgecolor=SURFACE, linewidth=2.0,
               zorder=3)
        for x, (value, bottom) in enumerate(zip(values, bottoms)):
            if value >= 7.0:
                ax.text(x, bottom + value / 2, f"{value:.0f}%", ha="center",
                        va="center", fontsize=8.5,
                        color="#ffffff" if k in (0, 1) else INK)
        bottoms += values

    ax.set_ylim(0, 100)
    ax.set_ylabel("share of paired world-decisions (%)", fontsize=10, color=INK_SECONDARY)
    legend = ax.legend(frameon=False, fontsize=9, loc="upper center",
                       bbox_to_anchor=(0.5, -0.09), ncol=3)
    for text in legend.get_texts():
        text.set_color(INK)
    return _finish(
        fig, out_dir / "fig4_failure_reasons.png",
        "Figure 4 · What goes wrong, and for which policy",
        f"{mission_kind.replace('_', ' ')} · outcome composition, hidden-world evaluation",
    )


# ---------------------------------------------------------------------------
# Figure 5 -- one world where the policies choose differently
# ---------------------------------------------------------------------------

def figure_example_world(rows, out_dir: Path, mission_kind="self_evacuation") -> Path:
    """Find a world where the two policies order at different times, and draw it."""
    from .runner import prepare_world
    from .worlds import build_experiment_world

    baseline = {
        int(r["world_id"]): r for r in rows
        if r["policy_id"] == "baseline_tuned_buffer" and r["mission_kind"] == mission_kind
    }
    chosen = None
    for r in rows:
        if r["policy_id"] != FROZEN_POLICY or r["mission_kind"] != mission_kind:
            continue
        if r["error_regime"] != "none" or float(r["latency_min"]) != 0.0:
            continue
        other = baseline.get(int(r["world_id"]))
        if other is None or not int(r["ordered"]) or not int(other["ordered"]):
            continue
        if abs(float(r["order_time_min"]) - float(other["order_time_min"])) >= 20.0:
            chosen = (r, other)
            break
    if chosen is None:
        raise RuntimeError("no world found where the policies differ materially")

    forecast_row, baseline_row = chosen
    world = build_experiment_world(
        int(forecast_row["world_id"]), str(forecast_row["archetype"]),
        int(forecast_row["master_seed"]),
    )
    prepared = prepare_world(world)
    grid = world.geometry.grid
    arrival = np.where(np.isfinite(prepared.arrival), prepared.arrival, np.nan)

    fig, ax = plt.subplots(figsize=(8.0, 7.4))
    ax.set_facecolor(SURFACE)
    extent = (0, grid.width_m / 1000.0, 0, grid.height_m / 1000.0)
    sequential = LinearSegmentedColormap.from_list(
        "wg_seq", ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]
    )
    image = ax.imshow(arrival, origin="lower", extent=extent, cmap=sequential,
                      alpha=0.92, zorder=1)
    ax.set_aspect("equal")

    network = world.geometry.network
    for route, colour, style in (
        (network.route("route_direct"), SERIES[1], "-"),
        (network.route("route_detour"), SERIES[2], "--"),
    ):
        for k, edge in enumerate(route.edges):
            ax.plot([edge.x0_m / 1000, edge.x1_m / 1000],
                    [edge.y0_m / 1000, edge.y1_m / 1000],
                    color=colour, linewidth=2.6, linestyle=style, zorder=4,
                    label=route.route_id.replace("route_", "") if k == 0 else None,
                    path_effects=None)
    approach = network.approach_route.edges[0]
    ax.plot([approach.x0_m / 1000, approach.x1_m / 1000],
            [approach.y0_m / 1000, approach.y1_m / 1000],
            color=INK_SECONDARY, linewidth=2.0, linestyle=":", zorder=4,
            label="responder approach")

    # Labels are offset away from the plot edge so none is clipped.
    for name, marker, offset in (
        ("village", "s", (10, 8)),
        ("destination", "*", (-14, 12)),
        ("base", "P", (-12, -18)),
    ):
        x, y = network.nodes[name]
        ax.scatter([x / 1000], [y / 1000], s=190 if marker == "*" else 120,
                   marker=marker, color=INK, edgecolors=SURFACE, linewidths=2.0,
                   zorder=6)
        ax.annotate(name, (x / 1000, y / 1000), textcoords="offset points",
                    xytext=offset, fontsize=9, color=INK,
                    ha="right" if offset[0] < 0 else "left")
    ix, iy = world.geometry.ignition_xy_m
    ax.scatter([ix / 1000], [iy / 1000], s=130, marker="X", color="#d03b3b",
               edgecolors=SURFACE, linewidths=2.0, zorder=6)
    ax.annotate("ignition", (ix / 1000, iy / 1000), textcoords="offset points",
                xytext=(9, 8), fontsize=9, color="#d03b3b")

    ax.set_xlabel("x (km)", fontsize=10, color=INK_SECONDARY)
    ax.set_ylabel("y (km)", fontsize=10, color=INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.02)
    bar.set_label("hidden fire arrival time (min)", fontsize=9, color=INK_SECONDARY)
    bar.ax.tick_params(colors=INK_SECONDARY, labelsize=8.5, length=0)
    bar.outline.set_visible(False)

    legend = ax.legend(frameon=False, fontsize=9, loc="lower left")
    for text in legend.get_texts():
        text.set_color(INK)

    summary = (
        f"tuned baseline ordered at {float(baseline_row['order_time_min']):.0f} min "
        f"via {baseline_row['route_id'] or '—'} → "
        f"{'completed' if int(baseline_row['mission_success']) else baseline_row['failure_reason']}\n"
        f"forecast-aware ordered at {float(forecast_row['order_time_min']):.0f} min "
        f"via {forecast_row['route_id'] or '—'} → "
        f"{'completed' if int(forecast_row['mission_success']) else forecast_row['failure_reason']}\n"
        f"Δ J = {float(forecast_row['loss']) - float(baseline_row['loss']):+.2f}"
    )
    ax.text(0.015, 0.975, summary, transform=ax.transAxes, va="top", ha="left",
            fontsize=9, color=INK,
            bbox=dict(boxstyle="round,pad=0.5", facecolor=SURFACE,
                      edgecolor=GRID, linewidth=1.0))
    return _finish(
        fig, out_dir / "fig5_example_world.png",
        "Figure 5 · One world, two policies, different decisions",
        f"world {forecast_row['world_id']} · {forecast_row['event_id']} · "
        f"{mission_kind.replace('_', ' ')} · perfect forecast, zero latency",
    )


def build_all(rows: Sequence[dict], out_dir: str | Path,
              mission_kind: str = "self_evacuation") -> list[Path]:
    """Build every figure and return the paths written."""
    out_dir = Path(out_dir)
    return [
        figure_skill_vs_value(rows, out_dir, mission_kind),
        figure_delta_heatmap(rows, out_dir, mission_kind),
        figure_frontier(rows, out_dir, mission_kind),
        figure_failure_reasons(rows, out_dir, mission_kind),
        figure_example_world(rows, out_dir, mission_kind),
    ]
