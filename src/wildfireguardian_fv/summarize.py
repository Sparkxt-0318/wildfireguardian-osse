"""Stage summaries: the numbers the reports quote, computed in one place.

A number in a report that was computed ad hoc in a terminal is a number nobody
can check.  Everything the written reports quote comes from
``raw_outputs/summary_stage<X>.json``, produced here from the committed rows.

Nothing in this module is inference.  Correlations and means are descriptive;
the paired intervals come from the runner's diagnostic bootstrap.  Formal
inference is ``wildfireguardian-evaluation``'s job (PROTOCOL.md section 15).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import RESULT_BANNER
from .records import read_outcomes

def _outcomes_path(root: Path, stage: str) -> Path:
    """The stage's row file, gzipped or not -- older runs wrote plain CSV."""
    gz = root / "raw_outputs" / f"outcomes_stage{stage}.csv.gz"
    return gz if gz.exists() else root / "raw_outputs" / f"outcomes_stage{stage}.csv"


MODE_LABEL = {
    "NONE": "baseline",
    "CONTROLLED_PERTURBATION": "mode_a",
    "INDEPENDENT_MODEL_FORECAST": "mode_b",
}


def _spearman(x: list[float], y: list[float]) -> float:
    """Rank correlation.  ``nan`` when either side is constant."""
    if len(x) < 3:
        return float("nan")
    def rank(v):
        order = np.argsort(np.asarray(v, dtype=float))
        out = np.empty(len(v), dtype=float)
        out[order] = np.arange(len(v), dtype=float)
        return out
    a, b = rank(x), rank(y)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _f(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def summarize_stage(root: str | Path, stage: str) -> dict:
    """Compute every quoted number for one stage."""
    root = Path(root)
    rows = read_outcomes(_outcomes_path(root, stage))
    deltas = json.loads(
        (root / "raw_outputs" / f"deltas_stage{stage}.json").read_text("utf-8")
    )["deltas"]

    actions: dict[str, Counter] = defaultdict(Counter)
    failures: dict[str, Counter] = defaultdict(Counter)
    outcomes: dict[str, Counter] = defaultdict(Counter)
    self_evac: dict[str, Counter] = defaultdict(Counter)
    threatened: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    losses: dict[str, list[float]] = defaultdict(list)
    skill: dict[tuple[str, str], list[float]] = defaultdict(list)

    for r in rows:
        key = MODE_LABEL.get(r["forecast_mode"], r["forecast_mode"])
        actions[key][r["action"]] += 1
        outcomes[key][r["outcome_state"]] += 1
        self_evac[key][r["self_evacuation_state"]] += 1
        losses[key].append(_f(r["loss"]))
        if r["threatened"] == "1":
            threatened[key][1] += 1
            threatened[key][0] += int(r["protection_failure"])
        if r["mission_success"] != "1":
            failures[key][r["failure_reason"] or r["reason"] or "UNRECORDED"] += 1
        csi = _f(r.get("forecast_csi", ""))
        if csi == csi and r["forecast_mode"] != "NONE":
            skill[(r["forecast_mode"], r["error_regime"])].append(csi)

    per_mode: dict[str, dict] = {}
    for key in sorted(actions):
        n = sum(actions[key].values())
        thr, fails = threatened[key][1], threatened[key][0]
        per_mode[key] = {
            "n_rows": n,
            "action_rate_act_now": actions[key]["ACT_NOW"] / n if n else float("nan"),
            "actions": dict(actions[key]),
            "mean_loss": float(np.mean(losses[key])) if losses[key] else float("nan"),
            "n_threatened_rows": thr,
            "n_protection_failures": fails,
            "protection_failure_rate_given_threatened": (
                fails / thr if thr else float("nan")
            ),
            "failure_reasons": dict(failures[key].most_common()),
            "outcome_states": dict(outcomes[key].most_common()),
            "self_evacuation_states": dict(self_evac[key].most_common()),
        }

    surfaces: dict[str, dict] = {}
    skill_vs_value: dict[str, dict] = {}
    for mode in ("CONTROLLED_PERTURBATION", "INDEPENDENT_MODEL_FORECAST"):
        cells, xs, ys = {}, [], []
        for key, rec in deltas.items():
            m, label = key.split("|", 1)
            if m != mode or not label.startswith("e"):
                continue
            e = float(label.split("_")[0][1:])
            d = float(label.split("_")[1][1:])
            cells[f"e{e:g}_d{d:g}"] = {
                "direction_bias_deg": e,
                "latency_min": d,
                "delta_j_mean": rec["delta_j_mean"],
                "ci_lo": rec["ci_lo"],
                "ci_hi": rec["ci_hi"],
                "resolved": int(not (rec["ci_lo"] <= 0.0 <= rec["ci_hi"])),
                "n_worlds": rec["n"],
                "mean_csi": (
                    float(np.mean(skill[(mode, label)]))
                    if (mode, label) in skill else float("nan")
                ),
            }
            if (mode, label) in skill:
                xs.append(float(np.mean(skill[(mode, label)])))
                ys.append(rec["delta_j_mean"])
        surfaces[mode] = cells
        # Does skill predict value overall, and at fixed latency?
        by_latency: dict[float, tuple[list[float], list[float]]] = defaultdict(
            lambda: ([], [])
        )
        for c in cells.values():
            if c["mean_csi"] == c["mean_csi"]:
                by_latency[c["latency_min"]][0].append(c["mean_csi"])
                by_latency[c["latency_min"]][1].append(c["delta_j_mean"])
        skill_vs_value[mode] = {
            "n_conditions": len(xs),
            "csi_min": min(xs) if xs else float("nan"),
            "csi_max": max(xs) if xs else float("nan"),
            "spearman_csi_vs_delta_j": _spearman(xs, ys),
            "spearman_within_latency": {
                f"{lat:g}": _spearman(a, b) for lat, (a, b) in sorted(by_latency.items())
            },
        }

    # The decisive comparison for "is skill sufficient?": conditions whose skill
    # is indistinguishable but whose decision value is not.
    equal_skill_pairs = []
    for mode, cells in surfaces.items():
        items = [c for c in cells.values() if c["mean_csi"] == c["mean_csi"]]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if abs(a["mean_csi"] - b["mean_csi"]) <= 0.01 and abs(
                    a["delta_j_mean"] - b["delta_j_mean"]
                ) >= 0.05:
                    equal_skill_pairs.append(
                        {
                            "mode": mode,
                            "csi": round(0.5 * (a["mean_csi"] + b["mean_csi"]), 4),
                            "a": f"e{a['direction_bias_deg']:g}_d{a['latency_min']:g}",
                            "b": f"e{b['direction_bias_deg']:g}_d{b['latency_min']:g}",
                            "delta_j_a": a["delta_j_mean"],
                            "delta_j_b": b["delta_j_mean"],
                            "sign_flip": int(
                                a["delta_j_mean"] * b["delta_j_mean"] < 0
                            ),
                        }
                    )

    return {
        "banner": RESULT_BANNER,
        "stage": stage,
        "n_rows": len(rows),
        "per_mode": per_mode,
        "surfaces": surfaces,
        "skill_vs_value": skill_vs_value,
        "equal_skill_different_value": equal_skill_pairs,
    }


def surface_markdown(summary: dict, mode: str) -> str:
    """A markdown table of one mode's response surface."""
    cells = summary["surfaces"].get(mode, {})
    if not cells:
        return "_(no cells)_"
    es = sorted({c["direction_bias_deg"] for c in cells.values()})
    ds = sorted({c["latency_min"] for c in cells.values()})
    lines = ["| latency \\ error | " + " | ".join(f"{e:g}°" for e in es) + " |"]
    lines.append("|---" * (len(es) + 1) + "|")
    for d in ds:
        row = [f"**{d:g} min**"]
        for e in es:
            c = cells[f"e{e:g}_d{d:g}"]
            mark = "" if c["resolved"] else " ᵘ"
            row.append(f"{c['delta_j_mean']:+.3f}{mark}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("ᵘ = the paired bootstrap interval covers zero (unresolved).")
    return "\n".join(lines)


def write_summary(root: str | Path, stage: str) -> Path:
    root = Path(root)
    summary = summarize_stage(root, stage)
    out = root / "raw_outputs" / f"summary_stage{stage}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return out
