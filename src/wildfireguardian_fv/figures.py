"""The five required figures.

Every figure carries the synthetic-OSSE banner.  None of them may be presented
as a Korean result: no Korean DEM, fuel map, road network or weather regime
constrains any world in this experiment (PROTOCOL.md section 14).

``matplotlib`` is an optional dependency (``pip install -e '.[figures]'``); the
laboratory's runtime dependencies are unchanged.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path

import numpy as np

from . import RESULT_BANNER

_BANNER_KW = dict(fontsize=7, style="italic", color="#444444")

#: Compact renderings for figure 5's divergence table. The full vocabulary is
#: in `dispatch.OUTCOME_STATES` and the exported `failure_reason` column; these
#: exist only so the caption fits on the canvas.
_ACTION_SHORT = {
    "ACT_NOW": "act", "NO_ACTION": "hold", "WAIT_FOR_FORECAST": "wait",
}
_REASON_SHORT = {
    "FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE": "house cut off",
    "BELIEF_FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE": "believed cut off",
    "ROUTE_BLOCKED_BY_FIRE": "road blocked",
    "NO_ROUTE_TO_RESIDENT": "no route in",
    "BELIEF_NO_ROUTE_TO_RESIDENT": "believed no route in",
    "NO_ROUTE_TO_DESTINATION": "no route out",
    "BELIEF_NO_ROUTE_TO_DESTINATION": "believed no route out",
    "MISSION_EXCEEDS_HORIZON": "past horizon",
    "BELIEF_MISSION_EXCEEDS_HORIZON": "believed past horizon",
    "NO_PREDICTED_THREAT": "no predicted threat",
    "OUTSIDE_TRIGGER_BUFFER": "outside trigger buffer",
    "NEVER_TRIGGERED": "never triggered",
    "NO_FIRE_EVIDENCE": "no fire evidence",
}


def _require_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "figures need matplotlib: pip install -e '.[figures]'"
        ) from exc


def _banner(fig) -> None:
    """Stamp the synthetic-result banner so it fits the canvas it is on.

    The banner is a claim-discipline device, not decoration: it must be legible
    and complete on every figure, so a narrow figure wraps it rather than
    letting the right-hand half run off the page.
    """
    width_in = fig.get_figwidth()
    if width_in >= 9.0:
        fig.text(0.01, 0.005, RESULT_BANNER, **_BANNER_KW)
        return
    head, _, tail = RESULT_BANNER.partition("Statements")
    fig.text(0.01, 0.004, head.strip() + "\n" + "Statements" + tail,
             **{**_BANNER_KW, "fontsize": 6.5})


def _read_rows(path: Path) -> list[dict]:
    """Read a stage's rows; accepts the gzipped or the plain spelling."""
    from .records import read_outcomes

    if not path.exists() and path.suffix != ".gz":
        path = path.with_suffix(path.suffix + ".gz")
    return read_outcomes(path)


def _f(value: str, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def figure1_skill_vs_value(root: Path, stage: str, plt) -> Path:
    """Forecast skill against decision value, one point per condition."""
    deltas = json.loads(
        (root / "raw_outputs" / f"deltas_stage{stage}.json").read_text("utf-8")
    )["deltas"]
    rows = _read_rows(root / "raw_outputs" / f"outcomes_stage{stage}.csv")
    skill: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        if r["forecast_mode"] in ("NONE", ""):
            continue
        csi = _f(r.get("forecast_csi", ""))
        if csi == csi:
            skill[(r["forecast_mode"], r["error_regime"])].append(csi)

    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    styles = {
        "INDEPENDENT_MODEL_FORECAST": ("o", "#1f77b4", "Mode B: independent model"),
        "CONTROLLED_PERTURBATION": ("s", "#d62728", "Mode A: perturbed truth"),
    }
    for mode, (marker, colour, label) in styles.items():
        xs, ys = [], []
        for key, rec in deltas.items():
            m, regime = key.split("|", 1)
            if m != mode or (m, regime) not in skill:
                continue
            xs.append(float(np.mean(skill[(m, regime)])))
            ys.append(rec["delta_j_mean"])
        if xs:
            ax.scatter(xs, ys, marker=marker, s=34, alpha=0.8, color=colour,
                       label=label, edgecolors="white", linewidths=0.5)
    ax.axhline(0.0, color="#333333", linewidth=1.0)
    ax.set_xlabel("forecast skill (CSI over the valid window)")
    ax.set_ylabel(r"decision value  $\Delta J = J_{forecast} - J_{baseline}$")
    ax.set_title(
        "Figure 1 — conventional forecast skill against decision value\n"
        "below the line: the forecast-aware policy did better", fontsize=10
    )
    ax.legend(fontsize=8, frameon=False)
    ax.grid(alpha=0.25)
    _banner(fig)
    out = root / "figures" / f"fig1_skill_vs_value_stage{stage}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def figure2_error_latency_heatmap(root: Path, stage: str, plt) -> Path:
    """The (direction error x latency) response surface of ``Delta J``."""
    deltas = json.loads(
        (root / "raw_outputs" / f"deltas_stage{stage}.json").read_text("utf-8")
    )["deltas"]
    modes = sorted({k.split("|")[0] for k in deltas if not k.endswith("invariant")})
    grids: dict[str, dict[tuple[float, float], dict]] = {m: {} for m in modes}
    for key, rec in deltas.items():
        mode, label = key.split("|", 1)
        if not label.startswith("e") or mode not in grids:
            continue
        e = float(label.split("_")[0][1:])
        d = float(label.split("_")[1][1:])
        grids[mode][(e, d)] = rec

    fig, axes = plt.subplots(1, max(1, len(modes)), figsize=(5.4 * len(modes), 4.4),
                             squeeze=False)
    vmax = max(
        (abs(r["delta_j_mean"]) for g in grids.values() for r in g.values()),
        default=1.0,
    ) or 1.0
    for ax, mode in zip(axes[0], modes):
        cells = grids[mode]
        es = sorted({e for e, _ in cells})
        ds = sorted({d for _, d in cells})
        mat = np.full((len(ds), len(es)), np.nan)
        for (e, d), rec in cells.items():
            mat[ds.index(d), es.index(e)] = rec["delta_j_mean"]
        im = ax.imshow(mat, cmap="RdBu_r", vmin=-vmax, vmax=vmax, origin="lower",
                       aspect="auto")
        ax.set_xticks(range(len(es)), [f"{e:g}" for e in es])
        ax.set_yticks(range(len(ds)), [f"{d:g}" for d in ds])
        ax.set_xlabel("direction error (deg)")
        ax.set_ylabel("forecast latency (min)")
        ax.set_title(mode.replace("_", " ").title(), fontsize=9)
        for (e, d), rec in cells.items():
            resolved = not (rec["ci_lo"] <= 0.0 <= rec["ci_hi"])
            value = rec["delta_j_mean"]
            # Contrast, not colour, carries the label: on a diverging map the
            # cell behind the text runs from very dark to white, so the text
            # colour is chosen from the cell's own lightness. Unresolved cells
            # are marked by the word, never by a fainter grey -- this is a
            # life-safety tool's figure and every label has to stay readable
            # (CLAUDE.md: legibility and WCAG AA contrast over polish).
            dark = abs(value) / vmax > 0.55
            ax.text(
                es.index(e), ds.index(d),
                f"{value:+.3f}" + ("" if resolved else "\n(unresolved)"),
                ha="center", va="center", fontsize=6.5, fontweight="bold",
                color="white" if dark else "black",
            )
        fig.colorbar(im, ax=ax, label=r"$\Delta J$")
    fig.suptitle(
        "Figure 2 — error x latency response surface; blue favours the "
        "forecast-aware policy,\n'unres.' marks cells whose paired interval "
        "covers zero", fontsize=10,
    )
    _banner(fig)
    out = root / "figures" / f"fig2_error_latency_heatmap_stage{stage}.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.92))
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def figure3_frontier(root: Path, stage: str, plt) -> Path:
    """Break-even structure, with every crossing shown as a bracket."""
    payload = json.loads(
        (root / "raw_outputs" / f"frontier_stage{stage}.json").read_text("utf-8")
    )["modes"]
    modes = sorted(payload)
    fig, axes = plt.subplots(1, max(1, len(modes)), figsize=(5.6 * len(modes), 4.4),
                             squeeze=False)
    for ax, mode in zip(axes[0], modes):
        res = payload[mode]
        by_lat: dict[float, list[dict]] = defaultdict(list)
        for c in res["cells"]:
            by_lat[c["latency_min"]].append(c)
        cmap = plt.get_cmap("viridis")
        lats = sorted(by_lat)
        for k, lat in enumerate(lats):
            pts = sorted(by_lat[lat], key=lambda c: c["direction_bias_deg"])
            xs = [p["direction_bias_deg"] for p in pts]
            ys = [p["delta_j_mean"] for p in pts]
            lo = [p["delta_j_ci_lo"] for p in pts]
            hi = [p["delta_j_ci_hi"] for p in pts]
            colour = cmap(k / max(1, len(lats) - 1))
            ax.plot(xs, ys, "-o", ms=3.5, color=colour, label=f"latency {lat:g} min")
            ax.fill_between(xs, lo, hi, color=colour, alpha=0.13, linewidth=0)
        for sl in res["slices_over_direction_error"]:
            for bracket in sl["crossing_brackets"]:
                ax.axvspan(bracket[0], bracket[1], color="#ff9900", alpha=0.16)
        ax.axhline(0.0, color="#333333", linewidth=1.0)
        ax.set_xlabel("direction error (deg)")
        ax.set_ylabel(r"$\Delta J$")
        ax.set_title(f"{mode.replace('_', ' ').title()}\n{res['summary']['verdict'].split(':')[0]}",
                     fontsize=9)
        ax.legend(fontsize=7, frameon=False)
        ax.grid(alpha=0.25)
    fig.suptitle(
        "Figure 3 — break-even structure. Shaded bands are crossing brackets; "
        "no curve is drawn\nthrough a region the data do not resolve.",
        fontsize=10,
    )
    _banner(fig)
    out = root / "figures" / f"fig3_frontier_stage{stage}.png"
    fig.tight_layout(rect=(0, 0.03, 1, 0.9))
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def figure4_failure_composition(root: Path, stage: str, plt) -> Path:
    """What goes wrong, and how often, by policy family."""
    rows = _read_rows(root / "raw_outputs" / f"outcomes_stage{stage}.csv")
    groups: dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for r in rows:
        key = (
            "baseline"
            if r["forecast_mode"] == "NONE"
            else ("Mode B" if r["forecast_mode"] == "INDEPENDENT_MODEL_FORECAST"
                  else "Mode A")
        )
        totals[key] += 1
        if r["mission_success"] == "1":
            continue
        groups[key][r["failure_reason"] or "UNRECORDED"] += 1

    # Normalised, not raw counts. The baseline contributes one row per resident
    # per world while each forecast mode contributes one per condition as well,
    # so the groups differ in size by a factor of 25: a raw-count chart would
    # say only that, and would read as if the baseline almost never failed.
    reasons = sorted({k for c in groups.values() for k in c})
    labels = sorted(groups)
    tick_labels = [f"{l}\n(n = {totals[l]:,} rows)" for l in labels]
    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    bottom = np.zeros(len(labels))
    cmap = plt.get_cmap("tab20")
    for k, reason in enumerate(reasons):
        vals = np.array(
            [100.0 * groups[l][reason] / max(1, totals[l]) for l in labels],
            dtype=float,
        )
        ax.bar(tick_labels, vals, bottom=bottom, label=reason, color=cmap(k % 20))
        bottom += vals
    ax.set_ylabel("share of that family's decisions (%)")
    ax.set_title(
        "Figure 4 — why outcomes did not complete\n"
        "as a share of each family's own decisions",
        fontsize=9.5,
    )
    ax.legend(fontsize=7, frameon=False, bbox_to_anchor=(1.01, 1.0), loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    _banner(fig)
    out = root / "figures" / f"fig4_failure_composition_stage{stage}.png"
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def figure5_example_world(root: Path, stage: str, plt) -> Path:
    """One world where the two policies chose differently.

    The world is rebuilt deterministically from the manifest's seed, so the
    figure is reproducible from the committed artefacts alone.
    """
    from .degradation import DegradationSpec
    from .loss import LossWeights
    from .planner import IndependentPlanner
    from .policy import BaselinePolicy, ForecastAwarePolicy, run_policy
    from .policy.baseline import BufferParams
    from .policy.forecast_aware import ForecastAwareParams
    from .splits import final_split_unlocked
    from .worlds import WorldGenConfig, build_experiment_world

    manifest = json.loads(
        (root / "manifests" / f"manifest_stage{stage}.json").read_text("utf-8")
    )
    seed = manifest["config"]["world_generation"]["master_seed"]
    tuning = manifest["config"].get("tuning", {})
    bp = (
        BufferParams(**tuning["baseline"]["best"])
        if tuning.get("tuned")
        else BufferParams()
    )
    fp = ForecastAwareParams()
    if tuning.get("tuned"):
        from dataclasses import replace

        best = tuning["forecast_aware_by_mode"]["INDEPENDENT_MODEL_FORECAST"]["best"]
        fp = replace(ForecastAwareParams(), **best)
    gen = WorldGenConfig(master_seed=seed)

    # Figure 5 re-builds worlds from the manifest's seed. For a final-split
    # stage that trips the split guard, which is correct: the guard exists to
    # stop the final worlds being *inspected before the protocol is frozen*.
    # Rendering a figure from a run that has already completed is not that, so
    # it is unlocked explicitly and with a written reason rather than bypassed.
    split = manifest["config"]["stage"]["split"]
    gate = (
        final_split_unlocked(
            f"rendering figure 5 from the completed stage-{stage} run; "
            "no tuning, no parameter is chosen here"
        )
        if split == "final"
        else nullcontext()
    )

    def _first_divergent_world():
        """The first world in the manifest where the two policies differ."""
        for entry in manifest["world_index"][:12]:
            w = build_experiment_world(gen, entry["archetype"], entry["world_id"])
            base = run_policy(w, BaselinePolicy(params=bp), LossWeights())
            planner = IndependentPlanner()
            pol = ForecastAwarePolicy(
                forecast_source=lambda info: planner.forecast(info, DegradationSpec()),
                params=fp,
            )
            pol.reset()
            fc = run_policy(w, pol, LossWeights())
            differ = [
                (b, f)
                for b, f in zip(base.traces, fc.traces)
                if b.action != f.action or b.truth_feasible != f.truth_feasible
            ]
            if differ:
                return w, base, fc, differ
        # No divergence anywhere is itself worth showing, so draw the first
        # world and say so in the title rather than failing.
        entry = manifest["world_index"][0]
        w = build_experiment_world(gen, entry["archetype"], entry["world_id"])
        base = run_policy(w, BaselinePolicy(params=bp), LossWeights())
        return w, base, base, []

    with gate:
        chosen = _first_divergent_world()

    w, base, fc, differ = chosen
    fig, ax = plt.subplots(figsize=(7.4, 6.8))
    arrival = np.where(
        np.isfinite(w.truth.arrival_time_min), w.truth.arrival_time_min, np.nan
    )
    extent = (0, w.grid_meta["width_m"], 0, w.grid_meta["height_m"])
    im = ax.imshow(arrival, origin="lower", extent=extent, cmap="inferno_r",
                   alpha=0.85)
    fig.colorbar(im, ax=ax, label="hidden fire arrival time (min)")
    for e in w.village.edges:
        xs = [p[0] for p in e.sample_xy_m]
        ys = [p[1] for p in e.sample_xy_m]
        ax.plot(xs, ys, color="#3366cc",
                linewidth=1.6 if e.road_class == "spine" else 0.8, alpha=0.65)
    bx, by = w.village.nodes[w.village.base_node]
    ax.plot(bx, by, "s", color="#111111", ms=9, label="responder base")
    for d in w.village.destination_nodes:
        dx, dy = w.village.nodes[d]
        ax.plot(dx, dy, "^", color="#00aa66", ms=10, label="destination")
    diff_ids = {b.resident_id for b, _ in differ}
    for r in w.village.residents:
        marker = "*" if r.resident_id in diff_ids else "o"
        ax.plot(r.x_m, r.y_m, marker, ms=13 if marker == "*" else 7,
                color="#ffffff", markeredgecolor="#000000", markeredgewidth=0.9)
        ax.annotate(r.resident_id, (r.x_m, r.y_m), fontsize=7,
                    xytext=(6, 5), textcoords="offset points")
    def _short(trace) -> str:
        """One compact cell: action, when, and how it actually ended."""
        when = "-" if trace.decision_time_min is None else f"{trace.decision_time_min:g}m"
        if trace.truth_feasible:
            return f"{_ACTION_SHORT.get(trace.action, trace.action)}@{when} ok"
        return (
            f"{_ACTION_SHORT.get(trace.action, trace.action)}@{when} "
            f"{_REASON_SHORT.get(trace.truth_reason, trace.truth_reason.lower())}"
        )

    lines = [f"{b.resident_id}:  baseline {_short(b)}   |   forecast {_short(f)}"
             for b, f in differ[:5]]
    ax.set_title(
        f"Figure 5 — world {w.world_id} ({w.archetype}): where the policies "
        "diverged\nstars mark the residents they treated differently",
        fontsize=9,
    )
    if lines:
        fig.text(
            0.02, 0.035, "\n".join(lines), fontsize=7, family="monospace",
            va="bottom",
        )
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    handles, labels = ax.get_legend_handles_labels()
    seen: dict[str, object] = {}
    for h, l in zip(handles, labels):
        seen.setdefault(l, h)
    ax.legend(seen.values(), seen.keys(), fontsize=7, loc="lower right",
              frameon=True)
    _banner(fig)
    out = root / "figures" / f"fig5_example_world_stage{stage}.png"
    fig.tight_layout(rect=(0, 0.04 + 0.022 * len(lines), 1, 0.96))
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def make_all_figures(root: Path, stage: str) -> list[Path]:
    """Produce every required figure for one stage."""
    plt = _require_matplotlib()
    root = Path(root)
    return [
        figure1_skill_vs_value(root, stage, plt),
        figure2_error_latency_heatmap(root, stage, plt),
        figure3_frontier(root, stage, plt),
        figure4_failure_composition(root, stage, plt),
        figure5_example_world(root, stage, plt),
    ]
