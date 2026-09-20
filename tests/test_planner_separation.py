"""The truth boundary, enforced rather than asserted in prose.

These are the tests that make ``reports/LEAKAGE_AUDIT.md`` mean something.
"""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_osse.experiment.runner import prepare_world
from wildfireguardian_osse.experiment.worlds import build_experiment_world
from wildfireguardian_osse.planner import (
    SealedTruth,
    TruthAccessViolation,
    assert_evaluator_context,
    in_planner_sandbox,
    make_controlled_perturbation_forecast,
    make_independent_model_forecast,
    planner_sandbox,
    score_forecast,
)
from wildfireguardian_osse.planner.view import PLANNER_TABLES


@pytest.fixture(scope="module")
def prepared():
    return prepare_world(build_experiment_world(0, "plain_uniform", 9090))


def test_sealed_truth_is_transparent_outside_and_opaque_inside(prepared):
    sealed = SealedTruth(prepared.truth, "truth")
    assert sealed.arrival_time_min.shape == prepared.arrival.shape
    with planner_sandbox():
        assert in_planner_sandbox()
        for attribute in ("arrival_time_min", "weather", "spot_events", "params"):
            with pytest.raises(TruthAccessViolation):
                getattr(sealed, attribute)
    assert not in_planner_sandbox()
    assert sealed.arrival_time_min.shape == prepared.arrival.shape


def test_sealed_truth_is_read_only():
    sealed = SealedTruth(object(), "truth")
    with pytest.raises(TruthAccessViolation):
        sealed.anything = 1


def test_sandbox_state_is_restored_after_an_exception():
    with pytest.raises(ValueError):
        with planner_sandbox():
            raise ValueError("boom")
    assert not in_planner_sandbox()


def test_evaluator_only_functions_refuse_to_run_in_a_sandbox(prepared):
    with planner_sandbox():
        with pytest.raises(TruthAccessViolation):
            assert_evaluator_context("x")
        with pytest.raises(TruthAccessViolation):
            make_controlled_perturbation_forecast(
                truth_arrival_min=prepared.arrival,
                grid=prepared.world.geometry.grid,
                origin_xy_m=prepared.world.geometry.ignition_xy_m,
                issue_time_min=30.0, horizon_min=90.0,
                regime=__import__(
                    "wildfireguardian_osse.planner.forecast", fromlist=["ErrorRegime"]
                ).ErrorRegime("none"),
                latency_min=0.0,
            )


def test_the_independent_model_needs_no_truth_at_all(prepared):
    """Mode B is built inside the sandbox: if it touched truth it would raise."""
    with planner_sandbox():
        forecast = make_independent_model_forecast(
            data=prepared.view.at(60.0), grid=prepared.world.geometry.grid,
            issue_time_min=60.0, horizon_min=90.0, latency_min=0.0,
        )
    assert forecast is not None
    assert forecast.provenance.value == "INDEPENDENT_MODEL_FORECAST"


def test_skill_scoring_is_evaluator_only(prepared):
    with planner_sandbox():
        forecast = make_independent_model_forecast(
            data=prepared.view.at(60.0), grid=prepared.world.geometry.grid,
            issue_time_min=60.0, horizon_min=90.0, latency_min=0.0,
        )
        with pytest.raises(TruthAccessViolation):
            score_forecast(forecast, prepared.arrival, prepared.world.geometry.grid)
    scores = score_forecast(forecast, prepared.arrival, prepared.world.geometry.grid)
    assert 0.0 <= scores.csi <= 1.0


# -- D_s: availability, not event time --------------------------------------

def test_planner_view_returns_only_available_records(prepared):
    for s in (20.0, 45.0, 90.0, 150.0):
        data = prepared.view.at(s)
        for name in PLANNER_TABLES:
            table = getattr(
                data,
                {"fire_detections": "fire_detections",
                 "fire_scan_log": "fire_scan_log",
                 "weather_observations": "weather_observations"}[name],
            )
            column = table.get("availability_time_min")
            if column is not None and len(column):
                assert float(np.max(column.astype(float))) <= s + 1e-9


def test_available_data_grows_monotonically(prepared):
    counts = [prepared.view.at(s).n_detections() for s in range(20, 181, 10)]
    assert counts == sorted(counts)
    assert counts[-1] > counts[0]


def test_a_record_processed_late_is_unavailable_until_delivered(prepared):
    """Filtering on event time would return strictly more than is legal."""
    table = prepared.view._tables["fire_detections"]
    event = np.asarray(table["event_time_min"], dtype=float)
    availability = np.asarray(table["availability_time_min"], dtype=float)
    s = float(np.median(event))
    by_event = int(np.count_nonzero(event <= s))
    legal = prepared.view.at(s).n_detections()
    assert by_event > legal


def test_planner_view_holds_no_truth_reference(prepared):
    """Nothing reachable from the view is the nature world."""
    view = prepared.view
    assert not hasattr(view, "truth")
    for table in view._tables.values():
        for column in table:
            assert "true_" not in column
            assert column != "kind"
    # static context only: terrain and coarse fuel class
    assert view.fuel_class.dtype.kind in "iu"


def test_no_seed_value_is_reachable_from_the_planner_view(prepared):
    """No seed reaches the planner, so hidden scenario identity is unreachable.

    Matched on **digit boundaries**, not as a bare substring: a short seed such
    as 9090 occurs by coincidence inside the decimal expansion of an ordinary
    timestamp, and a check that cries wolf on every float is a check nobody
    keeps.  This is the same rule the world-level scanner uses
    (``validation/leakage.py``).
    """
    import re

    seeds = set(prepared.world.seeds.all_seed_values())
    blob = repr(
        {k: {c: v.tolist() for c, v in t.items()} for k, t in prepared.view._tables.items()}
    )
    blob += repr(prepared.view.published_specs) + repr(prepared.world.geometry.as_dict())
    for seed in seeds:
        pattern = rf"(?<![\d.]){seed}(?![\d.])"
        assert re.search(pattern, blob) is None, f"seed {seed} reachable from the planner view"
