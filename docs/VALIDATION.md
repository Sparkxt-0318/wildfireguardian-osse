# VALIDATION

Validation here means: *does the synthetic system do what its own specification
says it does?* It does **not** mean, and cannot mean, agreement with real fires.

## 1. Validation worlds

Eight scenarios in `experiments/manifests/validation/`. Each has an expectation
that is analytic where possible and qualitative otherwise. They are executed by
`tests/test_validation_worlds.py` and by `wg-osse selftest`.

| # | Scenario | Setup | Expectation | Kind |
|---|---|---|---|---|
| V1 | `v1_uniform_no_wind` | flat, uniform fuel, `U = 0` | burned region is a **disc**; arrival time along the stencil axes is exact (`r / R0`); effective-speed ratio `max(r/T) / min(r/T) < 1.15` and no cell exceeds `R0` | analytic |
| V2 | `v2_uniform_constant_wind` | flat, uniform fuel, steady `U = 6` m/s toward the east | burned region elongated **downwind**; head/back extent ratio matches `(1+e)/(1−e)` within 20%; centroid displaced downwind | analytic |
| V3 | `v3_slope_only` | planar slope, `U = 0` | upslope > cross-slope > downslope extent, and the upslope/downslope ratio matches the model's `(1+e)/(1−e)` within 15% | analytic |
| V4 | `v4_fuel_discontinuity` | uniform fuel with a non-burnable band across the domain | **zero** burned cells beyond the band; burned cells on the near side `> 0` | analytic (hard) |
| V5 | `v5_wind_shift` | wind direction rotates 90° at `t = H/2` | the burned-region principal axis between `0…H/2` and `H/2…H` differ by `> 45°`; final shape is bilobate | qualitative |
| V6 | `v6_spotting_off` | as V2, `spotting.enabled = false` | identical to a run with the spotting module removed; no ignition record of type `spot` | analytic (hard) |
| V7 | `v7_spotting_on` | as V2, `spotting.enabled = true` | `>= 1` spot ignition; burned area `>=` V6's; at least one burned cell disconnected from the main front at its ignition time | qualitative (hard on the first two) |
| V8 | `v8_sensor_outage` | as V2, `missingness.mode = correlated_outage` | `>= 1` contiguous gap of `>= 2` scans in the scan log with `status = outage`; **truth identical to V2**, proving the outage touched only the observation layer | analytic (hard) |

"Hard" expectations are exact and are asserted; "qualitative" expectations use
generous tolerances and exist to catch sign errors and gross regressions, not to
certify fidelity.

### Note on V1's tolerance

An 8-neighbour stencil cannot produce an exact disc: it can only travel along
multiples of 45°, so an intermediate bearing is approximated by a staircase and
its path is up to 8.2% longer than the straight line (worst case at 22.5°). The
measured effective-speed ratio is **≈ 1.13**; the test bound is `< 1.15`.

Two things this bound is *not*. It is not a claim of circular exactness, and it
is not sensitive to `dt`: the burn-time credit ledger
(`docs/NATURE_MODEL.md#4`) makes arrival times identical at `dt = 1.0` and
`dt = 0.5`, and exact along the stencil directions. Tightening it requires a
richer stencil (`tasks/ROADMAP.md` item 2), not a parameter change. Treat the
residual as a known artefact, never as physical anisotropy
(`docs/FAILURE_MODES.md#L-06`).

## 2. Invariant tests

Run by `pytest`; these are the ones that make the laboratory trustworthy.

| Test | Asserts |
|---|---|
| `test_determinism.py::test_bitwise_reproduction` | two generations from the same `(config, seed)` produce identical sha256 for every file |
| `test_determinism.py::test_stream_independence` | changing `sensor_seed`/`missingness_seed` leaves **all** `truth/` checksums unchanged; changing `nature_seed` or `weather_seed` changes them |
| `test_determinism.py::test_seed_derivation_stability` | stream seeds are stable, documented values (guards against silently changing the derivation) |
| `test_no_leakage.py` | no planner-visible file contains a forbidden key, a seed value, the arrival-time array, or a real-instrument name; manifest labels are complete and consistent |
| `test_causality_prefix.py` | observations available by `H₁` are bit-identical when simulating to `H₁` and to `H₂ > H₁` |
| `test_timing.py` | `event <= acquisition <= processing <= availability` for every record; `available_at()` never returns a record early; reported `event_time` equals the snapped simulation time |
| `test_ros.py` | isotropy at `φ=0`, head/back/flank identities, monotonicity in `φ`, `LB` = axis ratio |
| `test_spread_analytic.py` | circular growth rate, non-burnable barrier, monotonicity of area in wind speed and in `spread_multiplier` |
| `test_observations.py` | detection count monotone in `p_detect_max`; geolocation error distribution matches `geoloc_sigma_m`; false-positive count matches the Poisson rate; FPs unlabelled in planner files |
| `test_missingness.py` | realised missing fraction matches `p_missing` (MCAR); outages are contiguous; `fire_correlated` failures occur only after the fire is within `fail_radius_m` |
| `test_storage.py` | manifest checksums verify; a failing world does not destroy completed ones; partial directories are never loaded |
| `test_cli.py` | `generate`/`validate`/`summarize` exit 0 on a good batch and non-zero on a corrupted world |

## 3. Statistical checks over a batch

`wg-osse summarize` computes, over all worlds in a batch:

* burned-area distribution, and its monotone response to `wind_speed_ms` and
  `spread_multiplier` (Spearman ρ, reported with n);
* detection-latency distribution (`availability_time − event_time`);
* realised missing fraction vs configured;
* fraction of worlds flagged `boundary_contact` (these must be excluded from
  area analyses — `docs/FAILURE_MODES.md#G-04`);
* fraction flagged `degenerate_no_ignition`;
* time-to-first-available-detection distribution — the single most
  decision-relevant summary of observation quality.

## 4. Discretisation accuracy and the validity envelope

The single most important numerical result in this repository, because it bounds
what any sweep over wind speed can mean.

The front is propagated on a discrete direction set. An **elliptical** front has
very different spread rates in different directions, so an intermediate bearing
must be approximated by a staircase of stencil moves whose rates differ sharply —
and the error grows with the eccentricity. Measured on a uniform flat landscape
(`dx = 30 m`, horizon 180 min, `dt` chosen so Courant ≤ 0.5, ignition well away
from the boundary), against the analytic ellipse area `π·a·b`:

| `U` (m/s) | `LB` | flank cells | area ratio, 8 dirs | **16 dirs (default)** | 32 dirs |
|---|---|---|---|---|---|
| 0 | 1.00 | 18.0 | 0.90 | **0.97** | 0.99 |
| 2 | 1.08 | 23.5 | — | **0.96** | 0.99 |
| 4 | 1.40 | 22.7 | — | **0.93** | 0.97 |
| 6 | 2.00 | 16.6 | 0.47 † | **0.85** | 0.93 |
| 8 | 2.91 | 11.0 | 0.31 † | **0.71** | 0.84 |
| 10 | 4.15 | 7.2 | 0.21 † | **0.56** | 0.71 |
| 12 | 5.75 | 4.8 | 0.14 † | **0.43** | 0.58 |

† the 8-direction column was measured with the earlier `c_lb = 0.14`, so it is
more eccentric at the same wind and is shown only to justify the default.

"flank cells" is `R_flank · horizon / cell_size`: how many cells the fire can
move *sideways* over the run. It is recorded per world as
`flank_cells_at_horizon`.

**Two consequences, both enforced in code.**

1. The default stencil is **16 directions** (`nature.stencil_max_offset = 2`),
   not 8. Eight directions under-predict the burned area by more than half at
   moderate wind, and — worse — make the area **non-monotone in wind speed**, so
   a sweep would show bigger fires at lower wind. That is an artefact that looks
   exactly like a finding (`docs/DECISIONS.md#d-016`).
2. A world records a `warnings` entry when `flank_cells_at_horizon < 8` or
   `max_eccentricity > 0.94`, the two places where the table turns bad.

**Validity envelope.** At `dx = 30 m` with the default coefficients and the
16-direction stencil, burned area is within ~15% of analytic for
`U ≲ 6 m/s` and monotone in wind speed up to `U ≈ 8 m/s`. The reference sweep
therefore keeps `wind_speed_ms ≤ 6`. Beyond that, use a finer grid, a longer
horizon, or 32 directions — and check `warnings` before believing an area.

## 5. What validation does **not** establish

* That burned areas, spread rates or shapes resemble any real fire.
* That the detection parameters resemble any real sensor
  (`docs/ASSUMPTIONS.md#D-08` is `UNKNOWN`).
* That a method which performs well here performs well anywhere else.

The laboratory certifies **internal consistency and control**, which is exactly
what the research question asks for (`docs/RESEARCH_QUESTION.md`), and nothing
more.
