# RESEARCH_QUESTION

## Primary question

> Can we generate reproducible wildfire-like synthetic worlds together with
> observation streams whose uncertainty, latency, cadence, missingness and
> failure modes are explicitly controlled?

"Controlled" is the operative word. The claim this repository must support is not
that the worlds are realistic, but that **every departure of the observations
from the truth is a consequence of a parameter someone wrote down.**

## Decomposition into testable sub-questions

| # | Sub-question | How it is answered | Evidence |
|---|---|---|---|
| Q1 | Is a generated world reproducible from `(config, master_seed)` alone? | Byte-level checksum comparison of two independent generations | `tests/test_determinism.py` |
| Q2 | Are the randomness streams independent, so that changing the sensor configuration does not change nature? | Regenerate with a different `sensor_seed`, assert truth checksums unchanged, and vice versa | `tests/test_determinism.py::test_stream_independence` |
| Q3 | Does the nature model reproduce the qualitative behaviours it claims (anisotropy, wind, slope, fuel discontinuity, spotting)? | Eight validation worlds with analytic or qualitative expectations | `docs/VALIDATION.md`, `tests/test_validation_worlds.py` |
| Q4 | Is the observation process free of truth leakage? | Forbidden-field/value scan + manifest visibility labels | `tests/test_no_leakage.py` |
| Q5 | Is the observation process free of *future* leakage? | Prefix-causality test: simulate to `H` and to `2H`, compare observations with `availability_time <= H` | `tests/test_causality_prefix.py` |
| Q6 | Are the four observation timestamps well defined and consistently ordered? | Invariant `event <= acquisition <= processing <= availability`, enforced at construction and tested | `docs/TIME_SEMANTICS.md`, `tests/test_timing.py` |
| Q7 | Can the controlled degradations be dialled independently (cadence, latency, noise, detection probability, missingness)? | Parameter sweeps + monotonicity checks on summary statistics | `tests/test_observations.py`, `tests/test_missingness.py` |
| Q8 | Does a batch survive partial failure without destroying completed worlds? | Fault-injection batch test | `tests/test_storage.py::test_batch_survives_world_failure` |

## What this repository deliberately does not ask

* Whether the synthetic fire resembles any particular real fire.
* Whether any routing, rescue or evacuation policy is good.
* Whether a forecast has operational value.

Those questions belong to other WildfireGuardian repositories and must not be
imported here (`docs/SCOPE.md`).

## Success criterion for Phase 1

Q1–Q8 are all answered affirmatively by automated tests, at least one batch of
100–500 worlds has been generated with per-world manifests, and the limitations
are documented (`docs/VALIDATION.md`, `docs/FAILURE_MODES.md`).
