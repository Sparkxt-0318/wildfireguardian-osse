"""``wg-osse`` command-line interface.

    wg-osse generate config.yaml            # a scenario or a sweep
    wg-osse validate world_000001/
    wg-osse summarize output_directory/

plus ``scenarios``, ``export-scenarios`` and ``selftest``.

Exit code 0 means every requested check passed; 1 means something is wrong with
the data; 2 means the command itself was malformed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Sequence

import yaml

from .. import GENERATOR_VERSION, MODEL_BANNER, __version__
from ..config import ConfigError, ScenarioConfig
from ..pipeline import generate_world
from ..scenarios.library import (
    build_validation_scenario,
    export_scenarios,
    validation_scenario_names,
)
from ..scenarios.sweep import expand_sweep, load_sweep
from ..storage.writer import BatchWriter, WorldWriter
from ..validation.checks import validate_world
from ..validation.summary import summarize_batch, summary_markdown

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------

def _is_sweep(payload: dict) -> bool:
    return "sweep" in payload or "base_scenario" in payload or "base" in payload


def _plan(path: Path, repeats: int) -> list[tuple[int, ScenarioConfig]]:
    """Expand a config file into the list of worlds to generate."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if _is_sweep(payload):
        return expand_sweep(load_sweep(path))
    cfg = ScenarioConfig.from_yaml(path)
    return [(k, cfg) for k in range(max(1, repeats))]


def cmd_generate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: no such config file: {config_path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        plan = _plan(config_path, args.repeats)
    except (ConfigError, KeyError) as exc:
        print(f"error: invalid configuration: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.limit:
        plan = plan[: args.limit]

    out_dir = Path(args.output)
    batch = BatchWriter(out_dir)
    print(f"{MODEL_BANNER}")
    print(f"generating {len(plan)} world(s) into {out_dir}")

    n_ok = 0
    started = time.time()
    for world_id, cfg in plan:
        try:
            world = generate_world(cfg, world_id)
            path = WorldWriter(out_dir, world_id).write(
                cfg=world.config,
                truth=world.truth,
                observations=world.observations,
                seeds=world.seeds,
            )
            summary = world.summary()
            batch.record_success(world_id, path, summary)
            n_ok += 1
            if args.verbose or len(plan) <= 12:
                print(
                    f"  world_{world_id:06d}: "
                    f"burned {summary['burned_area_ha']:.1f} ha, "
                    f"{summary['n_fire_detections']} detections, "
                    f"flags={world.truth.flags or '[]'}"
                )
            elif (n_ok % 25) == 0:
                print(f"  ... {n_ok}/{len(plan)} worlds")
        except Exception as exc:  # noqa: BLE001 - a batch must survive one bad world
            batch.record_failure(world_id, cfg.name, exc)
            print(f"  world_{world_id:06d}: FAILED ({type(exc).__name__}: {exc})",
                  file=sys.stderr)

    elapsed = time.time() - started
    n_failed = len(plan) - n_ok
    print(f"done: {n_ok} world(s) written, {n_failed} failed, {elapsed:.1f}s")
    if n_failed:
        print(f"failures logged to {batch.failures_path}", file=sys.stderr)
    return EXIT_OK if n_failed == 0 else EXIT_PROBLEMS


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------

def cmd_validate(args: argparse.Namespace) -> int:
    targets: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if (path / "manifest.json").exists():
            targets.append(path)
        else:
            targets.extend(sorted(p for p in path.glob("world_*") if p.is_dir()))
    if not targets:
        print("error: no world directories found", file=sys.stderr)
        return EXIT_USAGE

    total_problems = 0
    for world in targets:
        problems = validate_world(world)
        total_problems += len(problems)
        if problems:
            print(f"FAIL {world}")
            for problem in problems:
                print(f"    - {problem}")
        else:
            print(f"ok   {world}")
    if total_problems:
        print(f"\n{total_problems} problem(s) across {len(targets)} world(s)",
              file=sys.stderr)
        return EXIT_PROBLEMS
    print(f"\nall {len(targets)} world(s) passed")
    return EXIT_OK


# --------------------------------------------------------------------------
# summarize
# --------------------------------------------------------------------------

def cmd_summarize(args: argparse.Namespace) -> int:
    batch_dir = Path(args.batch_dir)
    if not batch_dir.is_dir():
        print(f"error: not a directory: {batch_dir}", file=sys.stderr)
        return EXIT_USAGE
    summary = summarize_batch(batch_dir)
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    report = summary_markdown(summary)
    if args.markdown:
        Path(args.markdown).write_text(report, encoding="utf-8")
    print(report)
    if summary["n_worlds"] == 0:
        print("error: no completed worlds found", file=sys.stderr)
        return EXIT_PROBLEMS
    return EXIT_OK


# --------------------------------------------------------------------------
# scenarios / export / selftest
# --------------------------------------------------------------------------

def cmd_scenarios(args: argparse.Namespace) -> int:
    for name in validation_scenario_names():
        cfg = build_validation_scenario(name)
        print(f"{name}\n    {cfg.description}")
    return EXIT_OK


def cmd_export_scenarios(args: argparse.Namespace) -> int:
    written = export_scenarios(args.directory)
    for path in written:
        print(f"wrote {path}")
    return EXIT_OK


def cmd_selftest(args: argparse.Namespace) -> int:
    """Generate and validate all eight validation worlds."""
    out_dir = Path(args.output)
    print(MODEL_BANNER)
    problems_total = 0
    for world_id, name in enumerate(validation_scenario_names()):
        cfg = build_validation_scenario(name)
        world = generate_world(cfg, world_id)
        path = WorldWriter(out_dir, world_id).write(
            cfg=world.config,
            truth=world.truth,
            observations=world.observations,
            seeds=world.seeds,
        )
        problems = validate_world(path)
        problems_total += len(problems)
        summary = world.summary()
        status = "ok  " if not problems else "FAIL"
        print(
            f"{status} {name}: burned {summary['burned_area_ha']:7.1f} ha, "
            f"{summary['n_fire_detections']:4d} detections, "
            f"{summary['n_outage_scans']} outage scans, "
            f"{summary['n_spot_ignitions']} spot ignitions"
        )
        for problem in problems:
            print(f"       - {problem}")
    if problems_total:
        return EXIT_PROBLEMS
    print("\nselftest passed")
    return EXIT_OK


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wg-osse",
        description=(
            "Observing System Simulation Experiment laboratory for "
            "WildfireGuardian. " + MODEL_BANNER
        ),
    )
    parser.add_argument(
        "--version", action="version",
        version=f"wildfireguardian-osse {__version__} (generator {GENERATOR_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate worlds from a scenario or sweep file")
    g.add_argument("config", help="scenario or sweep YAML file")
    g.add_argument("-o", "--output", default="worlds", help="output directory")
    g.add_argument("--repeats", type=int, default=1,
                   help="for a plain scenario, how many worlds to draw (different world ids)")
    g.add_argument("--limit", type=int, default=0, help="cap the number of worlds")
    g.add_argument("-v", "--verbose", action="store_true")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("validate", help="validate a world directory or a batch directory")
    v.add_argument("paths", nargs="+")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("summarize", help="summary statistics over a batch directory")
    s.add_argument("batch_dir")
    s.add_argument("--json", help="also write the summary as JSON here")
    s.add_argument("--markdown", help="also write the report as Markdown here")
    s.set_defaults(func=cmd_summarize)

    sc = sub.add_parser("scenarios", help="list the built-in validation scenarios")
    sc.set_defaults(func=cmd_scenarios)

    ex = sub.add_parser("export-scenarios", help="write the validation scenarios as YAML")
    ex.add_argument("directory", nargs="?", default="experiments/manifests/validation")
    ex.set_defaults(func=cmd_export_scenarios)

    st = sub.add_parser("selftest", help="generate and validate all eight validation worlds")
    st.add_argument("-o", "--output", default="worlds/validation")
    st.set_defaults(func=cmd_selftest)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
