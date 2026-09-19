# COMPLETED

Phase 1: the laboratory foundation. Outcomes only — the reasoning is in
`docs/DECISIONS.md`.

## Context system

* **Context documents written before implementation** — `README.md`,
  `AGENTS.md`, and the eleven documents in `docs/`. The three agent roles
  (Model Auditor, Implementation Engineer, Red-Team Validator) and their
  standards are in `AGENTS.md#2`.

## Agent A — Model Auditor

* **Mathematical state defined** (`docs/NATURE_MODEL.md#1`): the fire is exactly
  the arrival-time field `T`; everything else is derived from it.
* **Propagation assumptions stated** — elliptical Huygens propagation with a
  vector-combined wind/slope head direction, all coefficients labelled
  SYNTHETIC and uncalibrated.
* **Observation semantics stated** — for every planner-facing field, which
  operator computed it from which truth quantity at which time
  (`docs/OBSERVATION_MODEL.md#2`, `#3`).
* **Temporal semantics stated** — four times per record, with the usage rule and
  the reason the distinction is mandatory (`docs/TIME_SEMANTICS.md`).
* **Hidden-variable boundary drawn** — the executable list in
  `docs/OBSERVATION_MODEL.md#6`, and the one deliberate exception
  (static terrain and coarse fuel class) argued in `docs/DECISIONS.md#d-006`.
* **Leakage found in the design, before code:** sweep parameters would have
  reached planner-visible identifiers (`docs/DECISIONS.md#d-013`); aggregate
  truth would have sat in `manifest.json`; a false-positive label would have
  been trivially filterable (`#d-007`).

## Agent B — Implementation Engineer

* Package `src/wildfireguardian_osse/` with the specified layout: `landscape`,
  `nature`, `weather`, `observations`, `sensors`, `scenarios`, `storage`,
  `validation`, `cli`.
* Simulator, observation generators, configuration schema, storage, CLI and
  tests. Runtime dependencies: `numpy` and `PyYAML` only.
* Strict configuration: an unknown YAML key is an error, because a
  silently-ignored knob is a silently-invalid experiment.
* Named, hash-derived random streams with sub-streams
  (`docs/DECISIONS.md#d-004`).
* Incremental atomic storage: `.partial` directory, rename on completion,
  `batch_index.jsonl` / `failures.jsonl` (`#d-011`).
* CLI: `generate`, `validate`, `summarize`, plus `scenarios`,
  `export-scenarios`, `selftest`.

## Agent C — Red-Team Validator

Findings, and what happened to each.

| Attack | Finding | Outcome |
|---|---|---|
| Recover truth from a planner file | Scenario **descriptions quoted the wind speed** ("constant 6 m/s wind"), and descriptions are planner-visible | Fixed: validation descriptions are qualitative; the identifier scan now treats `_` as a separator, so `run_wind_6.0` is caught |
| Recover truth from a planner raster | `manifest.json` carried burned area and the master seed | Fixed: the manifest is a pure inventory; aggregates moved to `truth/world_summary.json` (`#d-005` layout, `docs/OBSERVATION_MODEL.md#5`) |
| Future-data leakage | Drawing latency jitter from the **same sub-stream** as the per-scan draws made a longer horizon change *earlier* detections | Fixed: jitter has its own sub-stream; prefix causality now tested three ways including under `fire_correlated` missingness |
| Future-data leakage | Weather variables shared one generator, so extending the horizon changed the past wind direction | Fixed: one sub-stream per variable (`rng.derive_seed` tag) |
| Seed contamination | — | No finding: truth checksums are invariant to sensor and missingness configuration (`test_stream_independence`) |
| Break deterministic reproduction | — | No finding: bitwise reproduction, and generation order does not matter |
| Physical / qualitative edge cases | **Burned area fell with increasing wind** up to ~2.2 m/s, because the length-to-breadth exponent gave eccentricity an infinite slope at zero wind | Fixed: `p_lb` raised to 1.5 (`#d-015`) |
| Physical / qualitative edge cases | **Burned area fell with increasing wind above ~4 m/s** with the 8-neighbour stencil — an artefact that looks exactly like a finding | Fixed: 16-direction stencil by default, `c_lb` lowered to 0.07, and the measured validity envelope documented (`#d-016`, `docs/VALIDATION.md#4`) |
| Physical / qualitative edge cases | Front propagation lost up to one `dt` per cell, running ~10% slow and making results `dt`-dependent | Fixed: burn-time credit ledger; arrival times are now exact along stencil directions and identical at `dt = 1.0` and `0.5` (`#d-014`) |
| Physical / qualitative edge cases | Correlated-outage records could have **negative duration** when the tick grid ran past the horizon | Fixed in `observations/missingness.py` |
| Physical / qualitative edge cases | A corrupt CSV **crashed `wg-osse validate`** instead of being reported | Fixed: tolerant table reading, and non-numeric columns are reported as problems |
| Leakage-scanner false positives | A uniform-fuel world has `fuel_class == fuel_multiplier` numerically; a world where nothing burned has constant truth rasters | Fixed: constant rasters are exempt (they carry no information), and the fuel check now asserts the published raster is an integer *coarsening* rather than testing equality |
| Edge cases | Ignition on a non-burnable cell, ignition at the domain edge, `dt` far too large, `p_detect_max = 0`, `p_missing = 1`, horizon shorter than one cadence | All handled; degenerate outcomes are **flagged**, not errors (`docs/FAILURE_MODES.md#G`) |

## Validation

* Eight validation worlds, each generated and validated by `wg-osse selftest`
  and asserted by `tests/test_validation_worlds.py`; none touches the domain
  boundary and none leaves the discretisation envelope.
* 158 tests covering determinism, stream independence, leakage, prefix
  causality, timing, the rate-of-spread identities, spread behaviour,
  observation operators, missingness, spotting, storage and the CLI.
* Measured discretisation accuracy against the analytic ellipse, and the
  resulting validity envelope, in `docs/VALIDATION.md#4`.

## First batch

384 worlds from `experiments/manifests/sweeps/reference_batch.yaml`, swept over
ignition point (3) x wind speed (4) x wind direction (4) x spread multiplier (2)
x spotting on/off (2) x detection latency (2). Summary kept at
`experiments/results/reference_batch_summary.md`.

* **384 completed, 0 failed**, and `wg-osse validate` passed on every world.
* Burned area 11.6 - 554 ha (median 96); 4 worlds flagged `boundary_contact`
  and must be excluded from area analyses.
* 14 worlds produced **no detection at all** - small fires below what the
  sensor can pick up. A real observation-quality outcome, not a failure.
* Monotonicity holds: burned area vs wind speed rho = 0.80, vs spread
  multiplier rho = 0.44.
* Detection latency spans 4 - 43 min across the two swept sensor variants.

## Definition of done — Phase 1

| Requirement | Status |
|---|---|
| package installs | yes (`pip install -e .`) |
| simulator runs | yes |
| observation process runs | yes |
| truth and observations separated | yes — layout, labels, scanner, causality test |
| deterministic reproduction | yes — `tests/test_determinism.py` |
| no-leakage tests exist | yes — `tests/test_no_leakage.py`, 4 attacks + 7 injections |
| timing semantics tested | yes — `tests/test_timing.py`, `tests/test_causality_prefix.py` |
| at least one batch generated | yes — 384 worlds |
| summary statistics produced | yes — `wg-osse summarize` |
| limitations documented | yes — `README.md`, `docs/VALIDATION.md#5`, `docs/FAILURE_MODES.md` |
| not integrated with another repo | correct — explicitly deferred (`docs/DECISIONS.md#d-001`) |
