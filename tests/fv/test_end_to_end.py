"""A complete miniature run, exercised end to end."""

from __future__ import annotations

import json

import numpy as np

from wildfireguardian_fv.degradation import DegradationSpec, ErrorGrid
from wildfireguardian_fv.loss import LossWeights
from wildfireguardian_fv.manifest import build_manifest, write_manifest
from wildfireguardian_fv.policy import BaselinePolicy
from wildfireguardian_fv.policy.forecast_aware import ForecastAwareParams
from wildfireguardian_fv.records import write_outcomes
from wildfireguardian_fv.runner import bootstrap_ci, paired_deltas, run_experiment


def test_miniature_experiment_produces_paired_rows(dev_world, dev_world_b, tmp_path):
    grid = ErrorGrid(direction_bias_deg=(0.0, 35.0), latency_min=(0.0, 30.0))
    out = run_experiment(
        [dev_world, dev_world_b],
        experiment_id="test_mini",
        grid=grid,
        modes=["INDEPENDENT_MODEL_FORECAST", "CONTROLLED_PERTURBATION"],
        baseline=BaselinePolicy(),
        forecast_params=ForecastAwareParams(),
        weights=LossWeights(),
    )
    n_res = len(dev_world.village.residents)
    expected = 2 * n_res * (1 + 2 * len(grid.points()))
    assert len(out.rows) == expected
    assert out.diagnostics["n_conditions"] == 4

    deltas = paired_deltas(out.conditions, LossWeights())
    for key, values in deltas.items():
        assert len(values) == 2, f"{key} is not paired across both worlds"
        mean, lo, hi = bootstrap_ci(values, n_boot=200)
        assert lo <= mean <= hi

    path = write_outcomes(tmp_path / "outcomes.csv", out.rows)
    text = path.read_text(encoding="utf-8").splitlines()
    assert len(text) == expected + 1
    assert "SYNTHETIC OSSE RESULT" in text[1]


def test_manifest_records_every_required_field(tmp_path, dev_world):
    m = build_manifest(
        experiment_id="test",
        stage="A",
        config={"x": 1},
        seed_manifest={"master_seed": 1},
        world_index=[{"world_id": dev_world.world_id}],
    )
    for key in (
        "experiment_id", "git_commit", "config_hash", "seed_manifest",
        "world_index", "versions", "banner",
    ):
        assert key in m
    for key in (
        "world_generator", "nature_model", "planner_model",
        "observation_model", "baseline", "policy", "loss",
    ):
        assert key in m["versions"]
    path = write_manifest(tmp_path / "m.json", m)
    assert json.loads(path.read_text(encoding="utf-8"))["stage"] == "A"


def test_skill_is_measured_independently_of_any_policy(conftest_executable_source):
    """Forecast skill must be computable without any policy existing."""
    from wildfireguardian_fv import skill

    code = conftest_executable_source(skill).lower()
    for banned in ("policy", "dispatch", "mission", "loss", "baseline"):
        assert banned not in code, (
            f"the skill module references {banned}; skill must be scored on "
            "its own terms so that 'does skill predict value' has content"
        )


def test_degraded_forecasts_change_decisions_somewhere(dev_world, dev_world_b):
    """A sanity check that the sweep axis actually does something."""
    from wildfireguardian_fv.planner import (
        ControlledPerturbationForecaster,
        IndependentPlanner,
    )
    from wildfireguardian_fv.runner import run_condition

    losses = []
    for spec in (
        DegradationSpec(label="e0_d0"),
        DegradationSpec(direction_bias_deg=55.0, latency_min=60.0, label="e55_d60"),
    ):
        res = [
            run_condition(
                w, spec, "CONTROLLED_PERTURBATION",
                baseline=BaselinePolicy(),
                forecast_params=ForecastAwareParams(),
                planner=IndependentPlanner(),
                perturber=ControlledPerturbationForecaster(),
                weights=LossWeights(),
            )
            for w in (dev_world, dev_world_b)
        ]
        losses.append(np.mean([r.forecast_aware.mean_loss(LossWeights()) for r in res]))
    assert losses[0] != losses[1], (
        "degrading the forecast changed nothing; the policy is not using it"
    )
