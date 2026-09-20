"""Seed separation between the laboratory and the experiment layer."""

from __future__ import annotations

from wildfireguardian_fv.rng import FV_STREAM_NAMES, FvSeedRegistry, derive_fv_seed
from wildfireguardian_osse.rng import STREAM_NAMES, derive_seed


def test_namespaces_are_disjoint():
    """The same (master, world, stream) must not collide across namespaces."""
    shared = set(FV_STREAM_NAMES) & set(STREAM_NAMES)
    assert not shared, f"stream names must not be shared: {shared}"
    for stream in FV_STREAM_NAMES:
        fv = derive_fv_seed(7, 3, stream)
        for lab_stream in STREAM_NAMES:
            assert fv != derive_seed(7, 3, lab_stream)


def test_streams_are_independent_of_each_other():
    reg = FvSeedRegistry.build(11, 2)
    seeds = [reg.seeds[s] for s in FV_STREAM_NAMES]
    assert len(set(seeds)) == len(seeds)


def test_sub_streams_are_independent():
    reg = FvSeedRegistry.build(11, 2)
    a = reg.generator("world_layout_seed", "village").random(5)
    b = reg.generator("world_layout_seed", "weather_regime").random(5)
    assert not (a == b).all()


def test_generators_are_reproducible():
    a = FvSeedRegistry.build(5, 1).generator("ignition_seed", "placement").random(8)
    b = FvSeedRegistry.build(5, 1).generator("ignition_seed", "placement").random(8)
    assert (a == b).all()


def test_changing_world_id_changes_every_stream():
    a = FvSeedRegistry.build(5, 1)
    b = FvSeedRegistry.build(5, 2)
    for s in FV_STREAM_NAMES:
        assert a.seeds[s] != b.seeds[s]
