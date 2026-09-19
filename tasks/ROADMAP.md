# ROADMAP

## Phase 1 — Laboratory foundation (current)

Goal: reproducible synthetic worlds + controlled observation streams, with
truth and observations provably separated.

- [x] Context documents (`docs/`, `AGENTS.md`)
- [x] Named, hash-derived random streams
- [x] Configuration schema + YAML loading + canonical config hashing
- [x] Landscape generation (terrain, fuels, slope/aspect)
- [x] Weather generation (AR(1) wind schedule)
- [x] Nature model (elliptical anisotropic front propagation)
- [x] Optional stochastic spotting
- [x] Fire observation stream (cadence, latency, noise, detection, FP/FN)
- [x] Weather observation stream (stations, error, latency)
- [x] Missingness models (MCAR, correlated outage, fire-correlated)
- [x] Four-stage observation time semantics
- [x] Incremental crash-safe storage with manifests and checksums
- [x] Leakage / determinism / timing / causality tests
- [x] Eight validation worlds
- [x] CLI `generate` / `validate` / `summarize`
- [x] First batch: 384 worlds generated, validated and summarised
- [x] Documented limitations

## Phase 2 — Fidelity and coverage (not started)

Ordered by expected value, highest first.

1. **Spatially varying wind field.** The largest single unrealism
   (`docs/ASSUMPTIONS.md#B-01`): stations currently differ only by noise, so
   spatial data assimilation cannot be studied at all.
2. **Better propagation stencil.** Replace 8-neighbour accumulation with a
   larger stencil or a fast-marching solver to remove the ~12% discretisation
   anisotropy (`docs/VALIDATION.md#note-on-v1s-tolerance`).
3. **Fireline intensity as a derived field**, enabling intensity-dependent
   detection instead of area-dependent only.
4. **Diurnal cycle** in wind and RH; moisture feedback on `R0`.
5. **Heterogeneous sensor fleets** — several fire sensors with different
   cadence/latency/footprint observing the same world.
6. **Scenario families with rare extremes** (long-tail wind, multi-ignition).
7. **Parquet output** as an optional fast path, keeping CSV as the contract.

## Phase 3 — Consumption interface (explicitly deferred)

Not to be started before Phase 2 is reviewed. When it is:

* a frozen, versioned read-only API (`storage/reader.py`) with
  `available_at(t)` as the only access path to observations;
* a conformance test-suite a consumer repository can run to prove it never
  reads `truth/` and never filters on `event_time`;
* **no** import of routing, rescue or forecast-value code into this repository —
  the dependency direction is one-way, outward (`docs/DECISIONS.md#d-001`).

## Known limitations carried forward

See `docs/VALIDATION.md#4` and `docs/FAILURE_MODES.md`. The two that most
constrain use today: spatially uniform wind, and uncalibrated synthetic spread
coefficients (`docs/ASSUMPTIONS.md#C-07`, `#D-08` — both `UNKNOWN`).
