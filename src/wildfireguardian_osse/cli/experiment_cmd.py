"""``wg-osse experiment`` -- run the forecast-value experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..experiment.benchmarks import run_benchmarks
from ..experiment.frontier import estimate_frontier
from ..experiment.manifest import build_manifest
from ..experiment.records import write_records
from ..experiment.runner import RunConfig, run_experiment
from ..experiment.tuning import FinalSplitTuningRefused, tune_baseline
from ..planner.forecast import ERROR_LEVELS, LATENCY_LEVELS_MIN
from ..policies.baseline import BaselineParams

DEFAULT_ROOT = "experiments/forecast_value_mve"


def _frozen_margin(root: Path) -> float:
    """Load the frozen, validation-tuned forecast safety margin."""
    path = root / "config/policy_frozen.json"
    if not path.exists():
        raise SystemExit(
            f"missing {path}: the forecast-aware policy must be tuned on the "
            "validation split before any run, for the same reason the baseline is."
        )
    return float(json.loads(path.read_text(encoding="utf-8"))["params"]["safety_margin_min"])


def _frozen_params(root: Path) -> BaselineParams:
    """Load the frozen, validation-tuned baseline.

    Refuses to fall back silently: a run that quietly used default parameters
    instead of the tuned ones would not be the experiment the protocol
    describes.
    """
    path = root / "config/baseline_frozen.json"
    if not path.exists():
        raise SystemExit(
            f"missing {path}: run `wg-osse experiment tune` first. The baseline "
            "must be tuned on the validation split before any run."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BaselineParams(**payload["params"])


def cmd_tune(args: argparse.Namespace) -> int:
    root = Path(args.root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    try:
        result = tune_baseline(
            split=args.split, n_worlds=args.worlds, master_seed=args.seed,
            progress=args.verbose,
        )
    except FinalSplitTuningRefused as exc:
        print(f"error: {exc}")
        return 2
    (root / "config/baseline_tuning.json").write_text(
        json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8"
    )
    print(f"tuned on {result.split} ({result.n_worlds} worlds): {result.best.as_dict()}")
    print(f"wrote {root/'config/baseline_tuning.json'}")
    print("Freeze the chosen parameters into config/baseline_frozen.json before running.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    for sub in ("raw_outputs", "manifests", "reports", "figures"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    cfg = RunConfig(
        experiment_id=args.experiment_id,
        split=args.split,
        n_worlds=args.worlds,
        master_seed=args.seed,
        stage=args.stage,
        baseline_params=_frozen_params(root),
        forecast_safety_margin_min=_frozen_margin(root),
    )
    print(
        f"stage {cfg.stage}: {cfg.n_worlds} worlds from the {cfg.split} split, "
        f"{len(ERROR_LEVELS)} error levels x {len(LATENCY_LEVELS_MIN)} latencies"
    )
    out = run_experiment(cfg, progress=args.verbose)
    rows = out["rows"]

    records = root / f"raw_outputs/evaluation_records_{cfg.experiment_id}.csv"
    write_records(rows, records)

    worlds_path = root / f"raw_outputs/world_index_{cfg.experiment_id}.json"
    worlds_path.write_text(json.dumps(out["worlds"], indent=2) + "\n", encoding="utf-8")

    manifest = build_manifest(
        cfg,
        data_files=[records, worlds_path],
        extra={"elapsed_s": out["elapsed_s"], "n_records": len(rows)},
    )
    manifest_path = root / f"manifests/manifest_{cfg.experiment_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"{len(rows)} records in {out['elapsed_s']:.1f}s")
    print(f"wrote {records}")
    print(f"wrote {manifest_path}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    root = Path(args.root)
    cfg = RunConfig(
        experiment_id=args.experiment_id, split=args.split, n_worlds=args.worlds,
        master_seed=args.seed, stage="A", baseline_params=_frozen_params(root),
        forecast_safety_margin_min=_frozen_margin(root),
        include_wait_variant=False,
    )
    out = run_experiment(cfg, progress=args.verbose)
    outcomes = [o.as_dict() for o in run_benchmarks(out["rows"])]
    path = root / "raw_outputs/benchmark_validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "note": (
                    "Validation cases, not evidence about prevalence. Passing "
                    "shows the apparatus can express the phenomenon."
                ),
                "split": cfg.split,
                "n_worlds": cfg.n_worlds,
                "outcomes": outcomes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for outcome in outcomes:
        print(f"{outcome['status']:17s} {outcome['benchmark']}")
    print(f"wrote {path}")
    return 0 if all(o["status"] == "DEMONSTRATED" for o in outcomes) else 1


def cmd_frontier(args: argparse.Namespace) -> int:
    from ..storage.tables import read_table

    root = Path(args.root)
    table = read_table(args.records)
    n = len(table["world_id"])
    rows = [{k: table[k][i] for k in table} for i in range(n)]
    for row in rows:
        row["world_id"] = int(float(row["world_id"]))
        row["loss"] = float(row["loss"])
        row["latency_min"] = float(row["latency_min"])

    payload = {}
    policies = sorted({str(r["policy_id"]) for r in rows if "forecast_aware" in str(r["policy_id"])})
    for mission_kind in ("self_evacuation", "assisted_evacuation"):
        for mode in ("CONTROLLED_PERTURBATION", "INDEPENDENT_MODEL_FORECAST"):
            levels = (
                [e.name for e in ERROR_LEVELS]
                if mode == "CONTROLLED_PERTURBATION"
                else ["independent_model"]
            )
            for policy_id in policies:
                slices = estimate_frontier(
                    rows, error_levels=levels, latency_levels=LATENCY_LEVELS_MIN,
                    mission_kind=mission_kind, forecast_mode=mode, policy_id=policy_id,
                )
                payload[f"{mission_kind}|{mode}|{policy_id}"] = [s.as_dict() for s in slices]
    path = root / "raw_outputs/frontier.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for key, slices in payload.items():
        print(key)
        for s in slices:
            crossings = "".join(f" [{a}->{b}]" for a, b in s["crossings"])
            print(f"    latency {s['latency_min']:5.0f}  {s['kind']:20s}{crossings}")
    print(f"wrote {path}")
    return 0


def cmd_figures(args: argparse.Namespace) -> int:
    from ..experiment.figures import build_all
    from ..storage.tables import read_table

    root = Path(args.root)
    table = read_table(args.records)
    n = len(table["world_id"])
    rows = [{k: table[k][i] for k in table} for i in range(n)]
    for row in rows:
        for key in ("world_id", "ordered", "mission_success", "master_seed"):
            row[key] = int(float(row[key]))
        for key in ("loss", "latency_min", "order_time_min", "skill_csi"):
            row[key] = float(row[key])
    paths = build_all(rows, root / "figures", mission_kind=args.mission_kind)
    for path in paths:
        print(f"wrote {path}")
    return 0


def register(sub) -> None:
    """Attach the ``experiment`` subcommands to the main parser."""
    parser = sub.add_parser("experiment", help="forecast-value experiment")
    inner = parser.add_subparsers(dest="experiment_command", required=True)

    t = inner.add_parser("tune", help="tune the baseline on the validation split")
    t.add_argument("--root", default=DEFAULT_ROOT)
    t.add_argument("--split", default="validation")
    t.add_argument("--worlds", type=int, default=20)
    t.add_argument("--seed", type=int, default=7717)
    t.add_argument("-v", "--verbose", action="store_true")
    t.set_defaults(func=cmd_tune)

    r = inner.add_parser("run", help="run a stage of the experiment")
    r.add_argument("--root", default=DEFAULT_ROOT)
    r.add_argument("--split", default="final")
    r.add_argument("--worlds", type=int, default=60)
    r.add_argument("--seed", type=int, default=20260920)
    r.add_argument("--stage", default="B")
    r.add_argument("--experiment-id", default="mve_stage_b")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(func=cmd_run)

    b = inner.add_parser("benchmark", help="constructed benchmark validation")
    b.add_argument("--root", default=DEFAULT_ROOT)
    b.add_argument("--split", default="development")
    b.add_argument("--worlds", type=int, default=16)
    b.add_argument("--seed", type=int, default=5150)
    b.add_argument("--experiment-id", default="benchmarks")
    b.add_argument("-v", "--verbose", action="store_true")
    b.set_defaults(func=cmd_benchmark)

    g = inner.add_parser("figures", help="build the report figures")
    g.add_argument("records")
    g.add_argument("--root", default=DEFAULT_ROOT)
    g.add_argument("--mission-kind", default="self_evacuation")
    g.set_defaults(func=cmd_figures)

    f = inner.add_parser("frontier", help="estimate the break-even frontier")
    f.add_argument("records")
    f.add_argument("--root", default=DEFAULT_ROOT)
    f.set_defaults(func=cmd_frontier)
