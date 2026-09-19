"""Storage: manifests, atomicity and batch resilience (``docs/DECISIONS.md#d-011``)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import fast_scenario, write_world
from wildfireguardian_osse.config import ScenarioConfig
from wildfireguardian_osse.pipeline import generate_and_write, generate_world
from wildfireguardian_osse.storage.manifest import sha256_file, verify_manifest
from wildfireguardian_osse.storage.reader import available_at, load_world
from wildfireguardian_osse.storage.tables import Table, read_table
from wildfireguardian_osse.storage.writer import BatchWriter, WorldWriter
from wildfireguardian_osse.validation.checks import REQUIRED_FILES, validate_world


def test_a_written_world_verifies(written_world):
    assert verify_manifest(written_world) == []
    for required in REQUIRED_FILES:
        assert (written_world / required).exists(), required


def test_manifest_lists_every_file_with_a_checksum(written_world):
    manifest = json.loads((written_world / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = written_world / entry["path"]
        assert entry["sha256"] == sha256_file(path)
        assert entry["bytes"] == path.stat().st_size
        assert entry["description"]


def test_verify_detects_a_missing_file(written_world):
    (written_world / "observations/fire_scan_log.csv").unlink()
    problems = verify_manifest(written_world)
    assert any("missing file" in p for p in problems)


def test_verify_detects_an_unlisted_file(written_world):
    (written_world / "observations/extra.csv").write_text("a,b\n1,2\n")
    problems = verify_manifest(written_world)
    assert any("not listed in the manifest" in p for p in problems)


def test_no_partial_directory_survives_a_successful_write(tmp_path):
    root = tmp_path / "batch"
    write_world(fast_scenario(), root, 4)
    assert list(root.glob(".world_*.partial")) == []
    assert (root / "world_000004").is_dir()


def test_a_partial_directory_is_never_loadable(tmp_path):
    root = tmp_path / "batch"
    path = write_world(fast_scenario(), root, 0)
    partial = root / ".world_000000.partial"
    path.rename(partial)
    (partial / "manifest.json").unlink()
    with pytest.raises(FileNotFoundError, match="not a completed world"):
        load_world(partial)


def test_rewriting_a_world_replaces_it_cleanly(tmp_path):
    root = tmp_path / "batch"
    first = write_world(fast_scenario(), root, 0)
    (first / "observations/stale.csv").write_text("x\n")
    second = write_world(fast_scenario(), root, 0)
    assert not (second / "observations/stale.csv").exists()
    assert verify_manifest(second) == []


def test_batch_survives_world_failure(tmp_path):
    """One bad world must not damage the worlds already written."""
    root = tmp_path / "batch"
    batch = BatchWriter(root)
    good = fast_scenario()

    for world_id in (0, 1):
        world = generate_world(good, world_id)
        path = WorldWriter(root, world_id).write(
            cfg=world.config, truth=world.truth,
            observations=world.observations, seeds=world.seeds,
        )
        batch.record_success(world_id, path, world.summary())

    # world 2 blows up mid-write
    try:
        world = generate_world(good, 2)
        writer = WorldWriter(root, 2)
        writer.partial_dir.mkdir(parents=True, exist_ok=True)
        (writer.partial_dir / "truth").mkdir()
        raise RuntimeError("synthetic failure during generation")
    except RuntimeError as exc:
        batch.record_failure(2, good.name, exc)

    for world_id in (3,):
        world = generate_world(good, world_id)
        path = WorldWriter(root, world_id).write(
            cfg=world.config, truth=world.truth,
            observations=world.observations, seeds=world.seeds,
        )
        batch.record_success(world_id, path, world.summary())

    completed = sorted(p.name for p in root.glob("world_*"))
    assert completed == ["world_000000", "world_000001", "world_000003"]
    assert list(root.glob(".world_*.partial")) == []
    for name in completed:
        assert verify_manifest(root / name) == []

    failures = [json.loads(l) for l in (root / "failures.jsonl").read_text().splitlines() if l]
    assert len(failures) == 1
    assert failures[0]["world_id"] == 2
    assert failures[0]["error_type"] == "RuntimeError"

    index = [json.loads(l) for l in (root / "batch_index.jsonl").read_text().splitlines() if l]
    assert [r["world_id"] for r in index] == [0, 1, 3]


def test_tables_round_trip_exactly(tmp_path):
    table = Table.from_columns(
        {"a": [1, 2, 3], "b": [0.1, np.inf, -2.5], "c": ["x", "y", "z"]}
    )
    path = tmp_path / "t.csv"
    table.to_csv(path)
    back = read_table(path)
    assert np.array_equal(back["a"], np.array([1.0, 2.0, 3.0]))
    assert np.array_equal(back["b"], np.array([0.1, np.inf, -2.5]))
    assert list(back["c"]) == ["x", "y", "z"]


def test_an_empty_table_still_writes_its_header(tmp_path):
    path = tmp_path / "empty.csv"
    Table.empty(["obs_id", "availability_time_min"]).to_csv(path)
    assert path.read_text() == "obs_id,availability_time_min\n"
    back = read_table(path)
    assert list(back) == ["obs_id", "availability_time_min"]
    assert all(v.size == 0 for v in back.values())


def test_loading_gives_only_planner_facing_streams(written_world):
    world = load_world(written_world)
    assert set(world.fire_detections) >= {"obs_id", "availability_time_min", "x_m"}
    assert "arrival_time_min" not in world.fire_detections
    streams = world.observations_available_at(30.0)
    for name, table in streams.items():
        assert np.all(table["availability_time_min"].astype(float) <= 30.0), name


def test_hidden_truth_needs_an_explicit_call(written_world):
    world = load_world(written_world)
    arrival = world.load_truth_array("arrival_time_min.npy")
    assert arrival.shape == (world.metadata["grid"]["ny"], world.metadata["grid"]["nx"])
    summary = world.load_world_summary()
    assert "burned_area_ha" in summary


def test_generate_and_write_returns_a_summary(tmp_path):
    path, summary = generate_and_write(fast_scenario(), tmp_path / "out", 7)
    assert path.name == "world_000007"
    assert summary["burned_area_ha"] > 0
    assert validate_world(path) == []


def test_a_degenerate_world_is_still_written(tmp_path):
    """No ignition is a flagged outcome, not an error (docs/FAILURE_MODES.md#G-03)."""
    cfg = fast_scenario(fuels={"kind": "uniform", "base_multiplier": 0.0})
    path, summary = generate_and_write(cfg, tmp_path / "out", 0)
    assert summary["burned_area_ha"] == 0.0
    metadata = json.loads((path / "metadata/world_metadata.json").read_text())
    assert "degenerate_no_ignition" in metadata["flags"]
    assert validate_world(path) == []
