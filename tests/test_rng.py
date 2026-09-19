"""Named random streams (``docs/DECISIONS.md#d-004``)."""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_osse.rng import STREAM_NAMES, SeedRegistry, derive_seed


def test_stream_names_are_the_documented_set():
    assert set(STREAM_NAMES) == {
        "master_seed",
        "nature_seed",
        "weather_seed",
        "spotting_seed",
        "sensor_seed",
        "missingness_seed",
    }


def test_derivation_is_deterministic_and_documented():
    # Pinned values: a change here re-randomises every world ever generated,
    # so it must be a conscious act, not a side effect.
    assert derive_seed(12345, 7, "nature_seed") == 583494783441401079
    assert derive_seed(12345, 7, "sensor_seed") == 6701238355491568078
    assert derive_seed(12345, 7, "nature_seed") == derive_seed(12345, 7, "nature_seed")


def test_streams_are_distinct_across_names_ids_and_tags():
    seeds = {
        derive_seed(1, 0, name) for name in STREAM_NAMES
    } | {
        derive_seed(1, world_id, "nature_seed") for world_id in range(8)
    } | {
        derive_seed(1, 0, "sensor_seed", tag) for tag in ("a", "b", "a:jitter")
    }
    # 6 streams + 8 world ids (one of which duplicates) + 3 tags, all distinct
    assert len(seeds) == 6 + 8 - 1 + 3


def test_unknown_stream_is_rejected():
    with pytest.raises(ValueError, match="unknown random stream"):
        derive_seed(1, 0, "not_a_stream")


def test_generators_are_independent_and_repeatable():
    registry = SeedRegistry.build(99, 3)
    a1 = registry.generator("nature_seed").standard_normal(64)
    a2 = registry.generator("nature_seed").standard_normal(64)
    b = registry.generator("sensor_seed").standard_normal(64)
    assert np.array_equal(a1, a2)
    assert not np.array_equal(a1, b)
    assert abs(float(np.corrcoef(a1, b)[0, 1])) < 0.35


def test_master_seed_is_not_confused_with_its_derived_stream():
    registry = SeedRegistry.build(12345, 7)
    payload = registry.as_dict()
    assert payload["master_seed"] == 12345
    assert payload["derived_stream_seeds"]["master_seed"] != 12345


def test_prefix_property_of_a_single_stream():
    """A longer draw from one stream starts with the shorter draw.

    This is why sub-streams matter: within a stream the prefix property holds,
    but a *later* draw shifts if an earlier one changes length.
    """
    registry = SeedRegistry.build(5, 0)
    short = registry.generator("weather_seed").standard_normal(10)
    long = registry.generator("weather_seed").standard_normal(40)
    assert np.array_equal(short, long[:10])
