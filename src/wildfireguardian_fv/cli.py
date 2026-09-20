"""``wg-fv`` -- the forecast-value experiment driver.

Subcommands, in the order a run uses them::

    wg-fv benchmarks   # constructed validation cases, development worlds
    wg-fv tune         # tune both policies, validation worlds only
    wg-fv run          # staged paired experiment; writes rows + manifest
    wg-fv frontier     # break-even analysis over a run's rows
    wg-fv figures      # the five required figures

Every subcommand writes into ``experiments/forecast_value_mve/`` and records a
manifest.  Nothing is computed twice from a different code path: the reports
are generated from the same artefacts a reader can open.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from . import RESULT_BANNER
from .benchmarks import run_benchmarks
from .degradation import ErrorGrid
from .frontier import CellEstimate, estimate_frontier
from .loss import LossWeights
from .manifest import build_manifest, file_sha256, write_manifest
from .planner import ControlledPerturbationForecaster, IndependentPlanner
from .policy import BaselinePolicy
from .policy.baseline import BufferParams
from .policy.forecast_aware import ForecastAwareParams
from .records import write_outcomes
from .runner import bootstrap_ci, paired_deltas, run_experiment
from .splits import final_split_read_count, final_split_unlocked
from .tuning import tune_baseline, tune_forecast_aware
from .worlds import GENERATION_AUDIT, WorldGenConfig, generate_split

DEFAULT_ROOT = Path("experiments/forecast_value_mve")

#: Staged world counts (PROTOCOL.md section 13).
STAGES: dict[str, dict] = {
    "A": {"split": "development", "n_worlds": 12,
          "purpose": "debug semantics"},
    "B": {"split": "validation", "n_worlds": 60,
          "purpose": "estimate variance and runtime"},
    "C": {"split": "final", "n_worlds": 60,
          "purpose": "frozen-protocol held-out reading, opened once"},
}


def _gen_config(args) -> WorldGenConfig:
    return WorldGenConfig(master_seed=args.master_seed)


#: The forecast modes the experiment runs, and the order it reports them in.
MODES = ("INDEPENDENT_MODEL_FORECAST", "CONTROLLED_PERTURBATION")


def _load_tuning(
    root: Path,
) -> tuple[BufferParams, dict[str, ForecastAwareParams], dict]:
    """Load tuned parameters: one baseline, one forecast policy *per mode*."""
    path = root / "config" / "tuned_policies.json"
    if not path.exists():
        return (
            BufferParams(),
            {m: ForecastAwareParams() for m in MODES},
            {"tuned": False},
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_mode = {
        mode: replace(ForecastAwareParams(), **rec["best"])
        for mode, rec in payload["forecast_aware_by_mode"].items()
    }
    return BufferParams(**payload["baseline"]["best"]), by_mode, payload


def _worlds(gen: WorldGenConfig, split: str, n: int, start: int = 0):
    return list(generate_split(gen, split, n, start_index=start))


def cmd_benchmarks(args) -> int:
    root = Path(args.root)
    gen = _gen_config(args)
    worlds = _worlds(gen, "development", args.n_worlds)
    baseline_params, fa_params, tuning = _load_tuning(root)
    outcomes, summaries = run_benchmarks(
        worlds,
        baseline=BaselinePolicy(params=baseline_params),
        forecast_params=fa_params["CONTROLLED_PERTURBATION"],
        planner=IndependentPlanner(),
        perturber=ControlledPerturbationForecaster(),
        weights=LossWeights(),
    )
    payload = {
        "banner": RESULT_BANNER,
        "n_worlds": len(worlds),
        "split": "development",
        "tuning_applied": tuning.get("tuned", True),
        "outcomes": [o.as_record() for o in outcomes],
        "condition_summaries": summaries,
        "note": (
            "Validation cases only. A DEMONSTRATED benchmark shows the "
            "experiment can express the regime; it is not evidence about how "
            "often the regime occurs."
        ),
    }
    out = root / "raw_outputs" / "benchmarks.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for o in outcomes:
        print(f"{o.status:16s} {o.name:32s} {o.detail}")
    print(f"\nwritten {out}")
    return 0


def cmd_tune(args) -> int:
    root = Path(args.root)
    gen = _gen_config(args)
    worlds = _worlds(gen, "validation", args.n_worlds)
    print(f"tuning on {len(worlds)} validation worlds", file=sys.stderr)
    base = tune_baseline(worlds)
    print(f"  baseline  best={base.best} J={base.best_loss:.4f} "
          f"({base.n_configurations} configs)", file=sys.stderr)
    by_mode = {}
    for mode in MODES:
        fa = tune_forecast_aware(worlds, mode=mode)
        print(f"  forecast[{mode}]  best={fa.best} J={fa.best_loss:.4f} "
              f"({fa.n_configurations} configs)", file=sys.stderr)
        by_mode[mode] = fa.as_record()
    payload = {
        "banner": RESULT_BANNER,
        "tuned": True,
        "split": "validation",
        "n_worlds": len(worlds),
        "master_seed": gen.master_seed,
        "baseline": base.as_record(),
        "forecast_aware_by_mode": by_mode,
        "note": (
            "The forecast-aware policy is tuned once per forecast mode, at the "
            "undegraded condition, and is then held fixed across every error "
            "regime within that mode. Tuning it only against the weaker "
            "forecast would confound 'an accurate forecast is not worth acting "
            "on' with 'this policy was set up not to act on one'."
        ),
    }
    out = root / "config" / "tuned_policies.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"written {out}")
    return 0


def _run_stage(args, stage: str) -> int:
    root = Path(args.root)
    spec = STAGES[stage]
    gen = _gen_config(args)
    n = args.n_worlds or spec["n_worlds"]
    baseline_params, fa_params, tuning = _load_tuning(root)
    grid = ErrorGrid()
    experiment_id = f"fv_mve_stage{stage}_{gen.master_seed}"

    def build():
        return _worlds(gen, spec["split"], n, start=1000 * ord(stage))

    if spec["split"] == "final":
        if not args.freeze_ack:
            print(
                "stage C reads the final split. Re-run with --freeze-ack "
                "to confirm the protocol is frozen (PROTOCOL.md section 3).",
                file=sys.stderr,
            )
            return 2
        with final_split_unlocked(
            "frozen-protocol Stage C evaluation, single pass"
        ):
            worlds = build()
    else:
        worlds = build()

    print(f"stage {stage}: {len(worlds)} {spec['split']} worlds x "
          f"{len(grid.points())} conditions x {len(args.modes)} modes",
          file=sys.stderr)
    output = run_experiment(
        worlds,
        experiment_id=experiment_id,
        grid=grid,
        modes=args.modes,
        baseline=BaselinePolicy(params=baseline_params),
        forecast_params=fa_params,
        weights=LossWeights(),
        progress=(lambda m: print("  " + m, file=sys.stderr)) if args.verbose else None,
    )
    rows_path = write_outcomes(
        root / "raw_outputs" / f"outcomes_stage{stage}.csv.gz", output.rows
    )
    manifest = build_manifest(
        experiment_id=experiment_id,
        stage=stage,
        config={
            "stage": spec,
            "n_worlds": len(worlds),
            "world_generation": {
                "master_seed": gen.master_seed,
                "nx": gen.nx, "ny": gen.ny, "cell_size_m": gen.cell_size_m,
                "horizon_min": gen.horizon_min, "dt_min": gen.dt_min,
            },
            "generation_audit": GENERATION_AUDIT,
            "error_grid": grid.as_record(),
            "modes": list(args.modes),
            "loss_weights": LossWeights().as_record(),
            "baseline_params": baseline_params.as_record(),
            "forecast_params_by_mode": {
                m: p.as_record() for m, p in fa_params.items()
            },
            "tuning": tuning,
        },
        seed_manifest={
            "master_seed": gen.master_seed,
            "lab_namespace": "wgosse|v1",
            "fv_namespace": "wgfv|v1",
            "streams": [w["lab_seeds"] for w in output.world_index[:1]],
        },
        world_index=output.world_index,
        data_hashes={rows_path.name: file_sha256(rows_path)},
        notes=(
            f"final_split_reads={final_split_read_count()}; "
            f"{output.diagnostics}"
        ),
    )
    write_manifest(root / "manifests" / f"manifest_stage{stage}.json", manifest)

    deltas = paired_deltas(output.conditions, LossWeights())
    summary = {}
    for (mode, label), values in sorted(deltas.items()):
        mean, lo, hi = bootstrap_ci(values)
        summary[f"{mode}|{label}"] = {
            "delta_j_mean": mean, "ci_lo": lo, "ci_hi": hi, "n": len(values)
        }
    (root / "raw_outputs" / f"deltas_stage{stage}.json").write_text(
        json.dumps({"banner": RESULT_BANNER, "deltas": summary}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {rows_path} ({len(output.rows)} rows)")
    return 0


def cmd_run(args) -> int:
    return _run_stage(args, args.stage)


def cmd_frontier(args) -> int:
    root = Path(args.root)
    src = root / "raw_outputs" / f"deltas_stage{args.stage}.json"
    payload = json.loads(src.read_text(encoding="utf-8"))["deltas"]
    out: dict[str, dict] = {}
    for mode in sorted({k.split("|")[0] for k in payload}):
        cells = []
        for key, rec in payload.items():
            m, label = key.split("|", 1)
            if m != mode or not label.startswith("e"):
                continue
            e = float(label.split("_")[0][1:])
            d = float(label.split("_")[1][1:])
            cells.append(
                CellEstimate(e, d, rec["delta_j_mean"], rec["ci_lo"],
                             rec["ci_hi"], rec["n"])
            )
        if cells:
            out[mode] = estimate_frontier(cells)
    dest = root / "raw_outputs" / f"frontier_stage{args.stage}.json"
    dest.write_text(
        json.dumps({"banner": RESULT_BANNER, "modes": out}, indent=2) + "\n",
        encoding="utf-8",
    )
    for mode, res in out.items():
        print(f"{mode}: {res['summary']['verdict']}")
    print(f"written {dest}")
    return 0


def cmd_summary(args) -> int:
    from .summarize import summarize_stage, surface_markdown, write_summary

    root = Path(args.root)
    path = write_summary(root, args.stage)
    summary = summarize_stage(root, args.stage)
    for mode, stats in summary["skill_vs_value"].items():
        print(
            f"{mode}: CSI {stats['csi_min']:.3f}-{stats['csi_max']:.3f}  "
            f"rho(CSI, dJ) = {stats['spearman_csi_vs_delta_j']:+.3f}"
        )
        print(surface_markdown(summary, mode))
        print()
    for key, stats in summary["per_mode"].items():
        print(
            f"{key:9s} act-now {stats['action_rate_act_now']:.1%}  "
            f"J {stats['mean_loss']:.4f}  "
            f"protection failures {stats['n_protection_failures']}"
            f"/{stats['n_threatened_rows']}"
        )
    print(f"\nwritten {path}")
    return 0


def cmd_figures(args) -> int:
    from .figures import make_all_figures

    paths = make_all_figures(Path(args.root), args.stage)
    for p in paths:
        print(p)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wg-fv", description=__doc__)
    p.add_argument("--root", default=str(DEFAULT_ROOT))
    p.add_argument("--master-seed", type=int, default=20260920)
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("benchmarks", help="constructed validation cases")
    b.add_argument("--n-worlds", type=int, default=12)
    b.set_defaults(func=cmd_benchmarks)

    t = sub.add_parser("tune", help="tune both policies on validation worlds")
    t.add_argument("--n-worlds", type=int, default=20)
    t.set_defaults(func=cmd_tune)

    r = sub.add_parser("run", help="run a staged paired experiment")
    r.add_argument("stage", choices=sorted(STAGES))
    r.add_argument("--n-worlds", type=int, default=0)
    r.add_argument(
        "--modes",
        nargs="+",
        default=list(MODES),
    )
    r.add_argument("--freeze-ack", action="store_true",
                   help="confirm the protocol is frozen (stage C only)")
    r.add_argument("--verbose", action="store_true")
    r.set_defaults(func=cmd_run)

    f = sub.add_parser("frontier", help="break-even analysis")
    f.add_argument("stage", choices=sorted(STAGES))
    f.set_defaults(func=cmd_frontier)

    s = sub.add_parser("summary", help="the numbers the reports quote")
    s.add_argument("stage", choices=sorted(STAGES))
    s.set_defaults(func=cmd_summary)

    g = sub.add_parser("figures", help="the five required figures")
    g.add_argument("stage", choices=sorted(STAGES))
    g.set_defaults(func=cmd_figures)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
