# FAILURE_MODES

Two kinds of failure are catalogued here: **failure modes we deliberately
simulate** (F-01…F-06) and **ways this laboratory itself can mislead you**
(L-01…L-08). The second list is the more important one.

## Part 1 — Simulated observation failure modes

| ID | Mode | How to enable | Notes |
|---|---|---|---|
| F-01 | **False negatives** — burning pixel not reported | lower `p_detect_max`, raise `detect_ref_area_m2` | the dominant failure early in a fire, when the burning area is smaller than `detect_ref_area_m2` |
| F-02 | **False positives** — report with no fire | `false_positive_rate_per_scan > 0` | unlabelled in planner files (`docs/DECISIONS.md#d-007`) |
| F-03 | **Geolocation error** — right fire, wrong place | `geoloc_sigma_m` | can place a report outside the domain; not clipped, on purpose |
| F-04 | **Latency** — right answer, too late | `processing_latency_min`, `delivery_latency_min`, `jitter_mean_min` | the reason the four-time scheme exists |
| F-05 | **Sensor outage / missingness** | `missingness.mode` ∈ `mcar`, `correlated_outage`, `fire_correlated` | see the warning below |
| F-06 | **Coarse footprint** — position quantised to a large pixel | `pixel_size_m` | interacts with F-03: total position error is footprint + noise |

### ⚠ F-05 is informative missingness

In `fire_correlated` mode a station's failure hazard rises as the fire
approaches. No truth value is written to any planner-visible file, so this is
**not leakage** — but the *pattern of absence* is correlated with the hidden
state, and a sufficiently clever consumer can invert it. Treat "my method got
better when stations started failing" as a red flag, not a result. Scenarios
that must exclude this channel should use `mcar` or `correlated_outage`.

## Part 2 — Ways this laboratory can mislead you

| ID | Failure | Symptom | Guard |
|---|---|---|---|
| L-01 | **Truth leakage** — a hidden field reaches a planner file | results far better than the observation quality can justify | forbidden key/value scan, `tests/test_no_leakage.py`, `wg-osse validate` |
| L-02 | **Future leakage** — an observation depends on `t > event_time` | performance that degrades when latency is *reduced* | prefix-causality test, `tests/test_causality_prefix.py` |
| L-03 | **Availability-time misuse** — a consumer filters on `event_time` | optimistic results that vanish in deployment | `storage/reader.available_at()`; documented in `docs/TIME_SEMANTICS.md#2` |
| L-04 | **Seed contamination** — streams not independent; changing a sensor changes the fire | paired comparisons across observation configs are confounded | hash-derived named streams, `tests/test_determinism.py::test_stream_independence` |
| L-05 | **Sweep-induced confounding** — a swept parameter correlates with fire size, so "harder observations" and "bigger fires" move together | apparent skill differences that are really size differences | sweep axes are recorded per world in `truth/nature_params.json`; always condition on final burned area when comparing |
| L-06 | **Discretisation artefacts mistaken for physics** — 8-neighbour anisotropy, or `dt` too large | octagonal "circles", spread speed depending on `dt` | CFL-style warning recorded in the manifest; `tests/test_validation_worlds.py` bounds the circular-spread error |
| L-07 | **Over-generalisation** — treating a synthetic result as a claim about real wildfires | any sentence of the form "this shows that in Korea…" | `docs/SCOPE.md#interpretation-limits`; the model header banner |
| L-08 | **Silent realism creep** — a generic sensor quietly acquiring a real instrument's name and numbers | a config with `viirs` or `goes` in it | `validation/leakage.py` rejects real-instrument names (`docs/DECISIONS.md#d-002`) |

## Part 3 — Operational failure modes of the generator

| ID | Failure | Behaviour |
|---|---|---|
| G-01 | one world in a batch raises | the world's partial directory is discarded, the error is appended to `failures.jsonl`, the batch continues (`docs/DECISIONS.md#d-011`) |
| G-02 | process killed mid-world | the partial directory `.world_XXXXXX.partial/` is left behind and is never mistaken for a complete world; `wg-osse summarize` reports it |
| G-03 | fire never ignites (ignition cell non-burnable) | the world is generated with an empty burned set and flagged `degenerate_no_ignition` in its metadata; it is not an error |
| G-04 | fire reaches the domain boundary | flagged `boundary_contact` in the world metadata; such worlds must be excluded from area-growth analyses |
| G-05 | `dt` violates the accuracy condition (Courant `max(R)·dt/dx > 1`) | warning recorded in the manifest and in the world metadata under `warnings` |
