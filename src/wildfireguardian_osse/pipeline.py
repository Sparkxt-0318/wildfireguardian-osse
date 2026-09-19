"""End-to-end generation of one world.

    HIDDEN NATURE WORLD  ->  OBSERVATION PROCESS  ->  AVAILABLE OBSERVATIONS

This module is the only place where the three stages are joined, and it is
deliberately short: it derives the seeds, runs nature, runs the observation
process, and writes.  Nothing else belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ScenarioConfig
from .nature.world import NatureTruth, simulate_nature
from .observations.process import ObservationBundle, run_observation_process
from .rng import SeedRegistry
from .storage.writer import WorldWriter, world_summary


@dataclass
class GeneratedWorld:
    """In-memory result of generating one world."""

    world_id: int
    config: ScenarioConfig
    seeds: SeedRegistry
    truth: NatureTruth
    observations: ObservationBundle

    def summary(self) -> dict:
        return world_summary(self.config, self.truth, self.observations, self.seeds)


def generate_world(cfg: ScenarioConfig, world_id: int = 0) -> GeneratedWorld:
    """Generate one world in memory.

    Args:
        cfg: the scenario configuration.
        world_id: index within a batch; enters the seed derivation, so two
            worlds from the same config but different ids are different worlds.

    Returns:
        A :class:`GeneratedWorld`.
    """
    seeds = SeedRegistry.build(cfg.master_seed, world_id)
    truth = simulate_nature(cfg, seeds)
    observations = run_observation_process(cfg, truth, seeds)
    return GeneratedWorld(
        world_id=world_id,
        config=cfg,
        seeds=seeds,
        truth=truth,
        observations=observations,
    )


def generate_and_write(
    cfg: ScenarioConfig, root: str | Path, world_id: int = 0
) -> tuple[Path, dict]:
    """Generate one world and write it atomically.

    Returns:
        ``(world_directory, summary)``.
    """
    world = generate_world(cfg, world_id)
    path = WorldWriter(root, world_id).write(
        cfg=world.config,
        truth=world.truth,
        observations=world.observations,
        seeds=world.seeds,
    )
    return path, world.summary()
