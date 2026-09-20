"""Frontier classification and the exported record contract."""

from __future__ import annotations

import pytest

from wildfireguardian_fv.frontier import (
    CellEstimate,
    classify_slice,
    estimate_frontier,
)
from wildfireguardian_fv.records import (
    OUTCOME_COLUMNS,
    OutcomeRow,
    assert_provenance_complete,
)


def _cell(e, d, mean, lo, hi, n=20):
    return CellEstimate(e, d, mean, lo, hi, n)


def test_a_resolved_sign_change_is_a_single_crossing():
    pts = [
        _cell(0.0, 0.0, -0.10, -0.15, -0.05),
        _cell(20.0, 0.0, -0.02, -0.06, -0.01),
        _cell(40.0, 0.0, 0.08, 0.03, 0.12),
    ]
    res = classify_slice("direction_bias_deg", 0.0, pts)
    assert res.classification == "SINGLE_CROSSING"
    assert len(res.crossings) == 1
    assert 20.0 < res.interpolated[0] < 40.0


def test_two_sign_changes_are_reported_as_multiple_not_smoothed():
    pts = [
        _cell(0.0, 0.0, -0.10, -0.14, -0.06),
        _cell(20.0, 0.0, 0.09, 0.04, 0.13),
        _cell(40.0, 0.0, -0.08, -0.12, -0.03),
    ]
    res = classify_slice("direction_bias_deg", 0.0, pts)
    assert res.classification == "MULTIPLE_CROSSINGS"
    assert len(res.crossings) == 2
    assert not res.monotone


def test_intervals_covering_zero_are_unresolved_not_a_crossing():
    pts = [
        _cell(0.0, 0.0, -0.01, -0.09, 0.07),
        _cell(20.0, 0.0, 0.01, -0.07, 0.09),
        _cell(40.0, 0.0, 0.02, -0.06, 0.10),
    ]
    res = classify_slice("direction_bias_deg", 0.0, pts)
    assert res.classification == "UNRESOLVED"
    assert res.crossings == ()


def test_no_crossing_is_named_by_which_policy_won():
    better = [_cell(e, 0.0, -0.1, -0.15, -0.05) for e in (0.0, 20.0, 40.0)]
    worse = [_cell(e, 0.0, 0.1, 0.05, 0.15) for e in (0.0, 20.0, 40.0)]
    assert (
        classify_slice("direction_bias_deg", 0.0, better).classification
        == "NO_CROSSING_FORECAST_BETTER"
    )
    assert (
        classify_slice("direction_bias_deg", 0.0, worse).classification
        == "NO_CROSSING_BASELINE_BETTER"
    )


def test_frontier_summary_reports_an_unresolved_grid_honestly():
    cells = [
        _cell(e, d, 0.001, -0.05, 0.05)
        for e in (0.0, 20.0)
        for d in (0.0, 30.0)
    ]
    out = estimate_frontier(cells)
    assert out["summary"]["verdict"].startswith("UNRESOLVED_EVERYWHERE")
    assert out["summary"]["n_resolved"] == 0
    assert out["summary"]["frontier_exists_in_grid"] is False


def test_frontier_does_not_assume_monotonicity():
    cells = [
        _cell(0.0, 0.0, -0.1, -0.14, -0.06),
        _cell(20.0, 0.0, 0.09, 0.04, 0.13),
        _cell(40.0, 0.0, -0.08, -0.12, -0.03),
        _cell(0.0, 30.0, -0.1, -0.14, -0.06),
        _cell(20.0, 30.0, -0.05, -0.09, -0.02),
        _cell(40.0, 30.0, -0.02, -0.05, -0.01),
    ]
    out = estimate_frontier(cells)
    assert out["summary"]["all_slices_monotone"] is False
    assert out["summary"]["frontier_exists_in_grid"] is True


def test_outcome_columns_are_stable_and_unique():
    assert len(OUTCOME_COLUMNS) == len(set(OUTCOME_COLUMNS))
    for required in (
        "world_id", "event_id", "policy_id", "error_regime", "latency_min",
        "loss", "mission_success", "travel_time", "resource_use",
        "responder_exposure", "failure_reason", "forecast_csi",
    ):
        assert required in OUTCOME_COLUMNS


def test_missing_provenance_fails_loudly():
    row = OutcomeRow({c: "x" for c in OUTCOME_COLUMNS})
    assert_provenance_complete([row])
    broken = OutcomeRow({**row.values, "split": ""})
    with pytest.raises(AssertionError):
        assert_provenance_complete([broken])


def test_a_crossing_is_found_across_an_unresolved_cell():
    """The cell nearest the crossing is the one most likely to be unresolved.

    Requiring the two sides of a sign change to be *adjacent* would hide every
    frontier the grid brackets well, which is exactly backwards. The bracket is
    reported wide instead, and flagged.
    """
    pts = [
        _cell(0.0, 0.0, -0.16, -0.20, -0.12),
        _cell(10.0, 0.0, -0.10, -0.14, -0.06),
        _cell(20.0, 0.0, -0.005, -0.05, 0.04),   # straddles zero
        _cell(35.0, 0.0, 0.06, 0.02, 0.10),
        _cell(55.0, 0.0, 0.11, 0.07, 0.15),
    ]
    res = classify_slice("direction_bias_deg", 0.0, pts)
    assert res.classification == "SINGLE_CROSSING"
    assert res.crossings == ((10.0, 35.0),)
    assert res.spans_unresolved is True
    assert 10.0 < res.interpolated[0] < 35.0


def test_a_bracket_between_adjacent_resolved_cells_is_not_flagged():
    pts = [
        _cell(0.0, 0.0, -0.10, -0.14, -0.06),
        _cell(20.0, 0.0, 0.08, 0.03, 0.12),
    ]
    res = classify_slice("direction_bias_deg", 0.0, pts)
    assert res.classification == "SINGLE_CROSSING"
    assert res.spans_unresolved is False


def test_outcome_rows_round_trip_through_gzip(tmp_path):
    """The gzipped spelling must hold exactly the same rows as the plain one."""
    from wildfireguardian_fv.manifest import file_sha256
    from wildfireguardian_fv.records import read_outcomes, write_outcomes

    rows = [
        OutcomeRow({c: f"{c}-{k}" for c in OUTCOME_COLUMNS}) for k in range(5)
    ]
    plain = write_outcomes(tmp_path / "outcomes.csv", rows)
    gz = write_outcomes(tmp_path / "outcomes.csv.gz", rows)

    assert read_outcomes(plain) == read_outcomes(gz)
    assert gz.stat().st_size < plain.stat().st_size or len(rows) < 10
    # The manifest hashes content, not container, so the two must agree.
    assert file_sha256(plain) == file_sha256(gz)
