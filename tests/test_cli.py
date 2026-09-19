"""The ``wg-osse`` command line (``docs/PROJECT_CONTEXT.md``)."""

from __future__ import annotations

import json

import pytest
import yaml

from conftest import fast_scenario
from wildfireguardian_osse.cli.main import EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE, main


@pytest.fixture()
def scenario_file(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(fast_scenario().to_dict()), encoding="utf-8")
    return path


@pytest.fixture()
def sweep_file(tmp_path):
    payload = {
        "base": fast_scenario().to_dict(),
        "sweep": {
            "mode": "grid",
            "max_worlds": 6,
            "master_seed": 777,
            "axes": [
                {"path": "weather.wind_speed_ms", "values": [0.0, 4.0]},
                {"path": "nature.spread_multiplier", "values": [0.8, 1.2]},
            ],
        },
    }
    path = tmp_path / "sweep.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_generate_validate_summarize(tmp_path, scenario_file, capsys):
    out = tmp_path / "worlds"
    assert main(["generate", str(scenario_file), "-o", str(out), "--repeats", "3"]) == EXIT_OK
    assert sorted(p.name for p in out.glob("world_*")) == [
        "world_000000", "world_000001", "world_000002"
    ]

    assert main(["validate", str(out)]) == EXIT_OK
    captured = capsys.readouterr().out
    assert "all 3 world(s) passed" in captured

    summary_json = tmp_path / "summary.json"
    report_md = tmp_path / "summary.md"
    assert main(["summarize", str(out), "--json", str(summary_json),
                 "--markdown", str(report_md)]) == EXIT_OK
    summary = json.loads(summary_json.read_text())
    assert summary["n_worlds"] == 3
    assert summary["n_failures"] == 0
    assert summary["burned_area_ha"]["n"] == 3
    assert "OSSE batch summary" in report_md.read_text()


def test_generate_from_a_sweep_file(tmp_path, sweep_file):
    out = tmp_path / "sweep_worlds"
    assert main(["generate", str(sweep_file), "-o", str(out)]) == EXIT_OK
    assert len(list(out.glob("world_*"))) == 4
    assert main(["validate", str(out)]) == EXIT_OK

    index = [json.loads(l) for l in (out / "batch_index.jsonl").read_text().splitlines() if l]
    winds = sorted({r["summary"]["sweep_axes"]["wind_speed_ms"] for r in index})
    assert winds == [0.0, 4.0]

    # every world keeps the base scenario name: swept values are hidden
    for world in out.glob("world_*"):
        metadata = json.loads((world / "metadata/world_metadata.json").read_text())
        assert metadata["scenario_name"] == "fast_test_world"


def test_limit_caps_the_number_of_worlds(tmp_path, sweep_file):
    out = tmp_path / "capped"
    assert main(["generate", str(sweep_file), "-o", str(out), "--limit", "2"]) == EXIT_OK
    assert len(list(out.glob("world_*"))) == 2


def test_validate_reports_a_corrupted_world(tmp_path, scenario_file, capsys):
    out = tmp_path / "worlds"
    main(["generate", str(scenario_file), "-o", str(out)])
    target = out / "world_000000" / "observations/fire_detections.csv"
    target.write_text(target.read_text() + "corrupt\n")
    assert main(["validate", str(out / "world_000000")]) == EXIT_PROBLEMS
    assert "FAIL" in capsys.readouterr().out


def test_validate_accepts_a_single_world_directory(tmp_path, scenario_file):
    out = tmp_path / "worlds"
    main(["generate", str(scenario_file), "-o", str(out)])
    assert main(["validate", str(out / "world_000000")]) == EXIT_OK


def test_generate_rejects_a_missing_file(tmp_path):
    assert main(["generate", str(tmp_path / "nope.yaml")]) == EXIT_USAGE


def test_generate_rejects_an_invalid_scenario(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"name": "x", "grd": {}}), encoding="utf-8")
    assert main(["generate", str(bad), "-o", str(tmp_path / "out")]) == EXIT_USAGE


def test_summarize_on_an_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["summarize", str(empty)]) == EXIT_PROBLEMS


def test_validate_on_a_directory_with_no_worlds(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["validate", str(empty)]) == EXIT_USAGE


def test_scenarios_lists_the_eight_validation_worlds(capsys):
    assert main(["scenarios"]) == EXIT_OK
    out = capsys.readouterr().out
    for k in range(1, 9):
        assert f"v{k}_" in out


def test_export_scenarios_writes_loadable_yaml(tmp_path):
    from wildfireguardian_osse.config import ScenarioConfig

    target = tmp_path / "manifests"
    assert main(["export-scenarios", str(target)]) == EXIT_OK
    files = sorted(target.glob("*.yaml"))
    assert len(files) == 8
    for path in files:
        cfg = ScenarioConfig.from_yaml(path)
        assert cfg.name == path.stem


def test_selftest_generates_and_validates_every_validation_world(tmp_path, capsys):
    out = tmp_path / "validation"
    assert main(["selftest", "-o", str(out)]) == EXIT_OK
    assert len(list(out.glob("world_*"))) == 8
    assert "selftest passed" in capsys.readouterr().out


def test_the_model_banner_is_printed_on_generation(tmp_path, scenario_file, capsys):
    main(["generate", str(scenario_file), "-o", str(tmp_path / "w")])
    assert "not an operational wildfire forecast model" in capsys.readouterr().out
