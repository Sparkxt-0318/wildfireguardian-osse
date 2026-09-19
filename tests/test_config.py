"""Configuration schema: strictness is the point."""

from __future__ import annotations

import pytest

from wildfireguardian_osse.config import ConfigError, ScenarioConfig

MINIMAL = {"name": "t", "nature": {"ignitions": [{"x_m": 100.0, "y_m": 100.0}]}}


def test_defaults_fill_in():
    cfg = ScenarioConfig.from_mapping(MINIMAL)
    assert cfg.grid.nx == 128
    assert cfg.nature.spotting.enabled is False
    assert cfg.observations.missingness.mode == "none"


def test_unknown_key_is_rejected_at_every_level():
    with pytest.raises(ConfigError, match="unknown key"):
        ScenarioConfig.from_mapping({**MINIMAL, "grd": {}})
    with pytest.raises(ConfigError, match="unknown key"):
        ScenarioConfig.from_mapping({**MINIMAL, "grid": {"nx": 8, "n_y": 8}})
    with pytest.raises(ConfigError, match="unknown key"):
        ScenarioConfig.from_mapping(
            {**MINIMAL, "observations": {"fire_sensors": [{"cadence_minutes": 10}]}}
        )


def test_a_world_without_an_ignition_is_rejected():
    with pytest.raises(ConfigError, match="at least one ignition"):
        ScenarioConfig.from_mapping({"name": "t"})


def test_ignition_outside_the_domain_is_rejected():
    with pytest.raises(ConfigError, match="outside the domain"):
        ScenarioConfig.from_mapping(
            {"name": "t", "grid": {"nx": 10, "ny": 10, "cell_size_m": 30.0},
             "nature": {"ignitions": [{"x_m": 10_000.0, "y_m": 0.0}]}}
        )


def test_sensor_finer_than_the_truth_is_rejected():
    with pytest.raises(ConfigError, match="finer than the nature grid"):
        ScenarioConfig.from_mapping(
            {**MINIMAL, "observations": {"fire_sensors": [{"pixel_size_m": 5.0}]}}
        )


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"time": {"horizon_min": -1.0}}, "horizon_min"),
        ({"observations": {"missingness": {"mode": "sometimes"}}}, "must be one of"),
        ({"observations": {"fire_sensors": [{"p_detect_max": 1.4}]}}, r"\[0, 1\]"),
        ({"weather": {"wind_speed_ms": -2.0}}, "wind_speed_ms"),
        ({"nature": {"ignitions": [{"x_m": 1.0, "y_m": 1.0}], "spread_multiplier": 0.0}},
         "spread_multiplier"),
    ],
)
def test_invalid_values_are_rejected(payload, message):
    with pytest.raises(ConfigError, match=message):
        ScenarioConfig.from_mapping({**MINIMAL, **payload})


def test_negative_latency_is_rejected():
    """A negative latency would let availability precede the event."""
    with pytest.raises(ConfigError, match="must be >= 0"):
        ScenarioConfig.from_mapping(
            {**MINIMAL,
             "observations": {"fire_sensors": [{"latency": {"processing_latency_min": -1.0}}]}}
        )


def test_duplicate_sensor_ids_are_rejected():
    with pytest.raises(ConfigError, match="duplicate fire sensor ids"):
        ScenarioConfig.from_mapping(
            {**MINIMAL,
             "observations": {"fire_sensors": [{"sensor_id": "a"}, {"sensor_id": "a"}]}}
        )


def test_config_hash_is_stable_and_sensitive():
    a = ScenarioConfig.from_mapping(MINIMAL)
    b = ScenarioConfig.from_mapping(MINIMAL)
    c = a.replace(master_seed=a.master_seed + 1)
    assert a.config_hash() == b.config_hash()
    assert a.config_hash() != c.config_hash()
    assert len(a.config_hash()) == 64


def test_yaml_round_trip(tmp_path):
    import yaml

    cfg = ScenarioConfig.from_mapping(MINIMAL)
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
    assert ScenarioConfig.from_yaml(path).config_hash() == cfg.config_hash()
