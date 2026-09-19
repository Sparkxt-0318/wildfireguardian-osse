# DECISIONS

Append-only decision log. Each entry records the decision, the alternatives that
were rejected, and the consequence. Do not edit an existing entry; supersede it
with a new one.

---

## D-001 — The repository is standalone
**Date:** 2026-09-19 · **Status:** accepted

The OSSE laboratory has no dependency on routing, rescue, forecast-value or data
repositories, and must not gain one in Phase 1.

*Rejected:* building the OSSE inside the evaluation repository (faster initially,
but the lab would then be shaped by one consumer and could not be reused).

*Consequence:* outputs are plain `.npy`/`.csv`/`.json`; any consumer can read a
world without importing this package.

---

## D-002 — Generic sensors only, never named instruments
**Date:** 2026-09-19 · **Status:** accepted

No sensor is named after, or parameterised from, a real instrument. A sensor is
described only by its **behavioural parameters** (cadence, latency, pixel size,
detection probability, geolocation error, missingness).

*Rejected:* calling a stream "VIIRS-like" or "GK2A-like" with plausible-looking
numbers. Guessed specifications would silently acquire the authority of the real
instrument's name and would contaminate every downstream conclusion.

*Consequence:* sensor identifiers are neutral (`fire_sensor_a`, `wx_net_a`).
Real specifications are recorded as `UNKNOWN` in `docs/ASSUMPTIONS.md#D-08`
until verified from a primary source. A validator rejects any sensor id or label
matching a list of real-instrument names (`validation/leakage.py`).

---

## D-003 — Transparent synthetic nature model, not CFD / WRF-SFIRE
**Date:** 2026-09-19 · **Status:** accepted

Phase 1 uses an elliptical, wind- and slope-driven front-propagation model over
a raster (`docs/NATURE_MODEL.md`).

*Rejected:* a coupled fire–atmosphere solver. It would be uncheckable by hand,
far too slow for hundreds of worlds, and would create the illusion of realism
that `docs/SCOPE.md` explicitly disclaims.

*Consequence:* the model is labelled everywhere as *"Synthetic nature model for
controlled experiments; not an operational wildfire forecast model."* Analytic
checks (circular spread under no wind/no slope) become possible.

---

## D-004 — Named, hash-derived, independent random streams
**Date:** 2026-09-19 · **Status:** accepted

All randomness derives from one `master_seed`. A stream seed is
`int.from_bytes(sha256(f"wgosse|v1|{master_seed}|{world_id}|{stream}").digest()[:8], "big")`
and is used to build an independent `numpy.random.Generator`.

*Rejected:* (a) one global generator — consumption order then couples unrelated
components, so adding a sensor changes the fire; (b) `seed + k` offsets — cheap
but correlated and fragile.

*Consequence:* streams `master_seed`, `nature_seed`, `weather_seed`,
`spotting_seed`, `sensor_seed`, `missingness_seed` are independent. Changing the
sensor configuration provably cannot change the truth
(`tests/test_determinism.py::test_stream_independence`).

---

## D-005 — Four observation timestamps, always
**Date:** 2026-09-19 · **Status:** accepted

Every observation record carries `event_time_min`, `acquisition_time_min`,
`processing_time_min`, `availability_time_min`. An observation may be used by a
consumer only at or after its `availability_time_min`.

*Rejected:* a single `timestamp` column with a documented "latency" constant —
it makes the legal-use rule unenforceable and invites accidental look-ahead.

*Consequence:* latency components are non-negative by construction, so the
ordering invariant holds structurally (`docs/TIME_SEMANTICS.md`).

---

## D-006 — Static context is planner-visible; dynamic truth is not
**Date:** 2026-09-19 · **Status:** accepted

`observations/static_context/` contains elevation and fuel-class rasters.

*Rationale:* terrain and fuel maps are, in reality, known before an incident.
They contain no temporal information and therefore cannot reveal the fire's
future. The **ignition point, the wind time series, the spread parameters and
the arrival-time field remain hidden**, so static context alone does not
determine the fire.

*Rejected:* hiding terrain entirely (unrealistic — a planner that does not know
where the mountains are is not the planner we want to study), and exposing the
continuous `fuel_multiplier` used by the model (that *is* a model parameter;
only the coarse integer class is exposed).

*Consequence:* the leakage scanner allow-lists exactly these two files, by name,
with this rationale attached in the manifest.

---

## D-007 — False positives are unlabelled in planner-facing files
**Date:** 2026-09-19 · **Status:** accepted

Spurious detections appear in `observations/fire_detections.csv` with no field
distinguishing them from real ones. The ledger of which detections were spurious
lives in `truth/detection_ledger.csv`.

*Rejected:* an `is_false_positive` column (convenient for analysis, fatal for
the experiment — a planner could filter on it).

---

## D-008 — Scan logs are published even when nothing is detected
**Date:** 2026-09-19 · **Status:** accepted

`observations/fire_scan_log.csv` records that a scan happened and when its result
became available, including scans that produced zero detections.

*Rationale:* "no detections in this scan" is itself an observation, and omitting
it would make absence ambiguous between *not observed* and *observed as empty*.
The log contains no information about the fire beyond that distinction.

---

## D-009 — Fire-correlated missingness is informative, and that is intentional
**Date:** 2026-09-19 · **Status:** accepted

In `fire_correlated` mode, a weather station's failure hazard rises as the fire
approaches, so the *absence* of data is correlated with the hidden state.

*This is not leakage* (no truth value is written to a planner-facing file), but
it **is** an information channel, and a consumer could exploit it. It is a
deliberate research knob for studying informative missingness and is flagged in
`docs/FAILURE_MODES.md#F-05`. Scenarios that must avoid it use `mcar` or
`correlated_outage`.

---

## D-010 — Residence time affects observability, not propagation
**Date:** 2026-09-19 · **Status:** accepted

Once a cell has ignited it remains a valid spread source for the rest of the
simulation. `residence_time_min` defines only the window during which a cell is
*actively burning* and therefore observable.

*Rejected:* gating propagation on residence time. With slow spread the front can
then self-extinguish for purely numerical reasons, destroying the analytic
circular-spread check and introducing a silent dependence on `dt`.

---

## D-011 — Incremental, atomic per-world storage
**Date:** 2026-09-19 · **Status:** accepted

Each world is written into `.world_XXXXXX.partial/` and renamed to
`world_XXXXXX/` only after `manifest.json` is written. A completed world is
appended to `batch_index.jsonl`; a failure is appended to `failures.jsonl` and
the batch continues.

*Consequence:* a crash or a single bad parameter combination cannot destroy
already-completed worlds, and a partially written world is never mistaken for a
complete one (`tests/test_storage.py`).

---

## D-012 — Determinism is claimed per-environment, not cross-platform
**Date:** 2026-09-19 · **Status:** accepted

Bit-identical reproduction is asserted for a fixed `(config, seed, numpy
version, platform)`. Cross-platform floating-point bit-identity is **not**
claimed. Integer/categorical outputs (detection counts, ignition cells, event
ordering) are expected to be stable more broadly but this is untested.

---

## D-013 — Swept parameters must not reach planner-visible identifiers
**Date:** 2026-09-19 · **Status:** accepted

`metadata/world_metadata.json` is planner-visible and carries the scenario
`name`, `description` and `tags`. A sweep over wind speed or spread multiplier
that encoded its values there (`sweep_u6_dir090`) would hand a planner the
hidden parameters in plain text.

Therefore: a sweep axis targeting `name`, `description` or `tags` is **rejected**
(`scenarios/sweep.py`), every world in a sweep keeps the base scenario's name,
and the swept values are recorded only in `truth/world_summary.json`.

The leakage scanner checks the result independently rather than trusting the
sweep code: it reads the sweep axis values from hidden truth and fails if any of
them appears as a substring of a planner-visible identifier
(`validation/leakage.py`).

*Consequence:* worlds in a batch are told apart by `world_id`, not by a
descriptive name. That is the intended experience for a blind consumer.

---

## D-014 — A burn-time credit ledger in the propagation scheme
**Date:** 2026-09-19 · **Status:** accepted

Each cell records how many minutes of "being alight" it has already been
credited with as a spread source; each step credits exactly the difference.

*Rationale:* a cell whose interpolated arrival time falls part-way through a
step is only discovered at the end of that step. Without the ledger it loses the
remainder of the step, the fire runs ~10% slow at `dt = 1 min`, and the error
depends on `dt` — so a scenario's behaviour would change when the step changed.

*Consequence:* arrival times on a uniform no-wind landscape are exact
(`10.0, 20.0, 30.0 …` min per 30 m cell at `R0 = 3 m/min`) and identical for
`dt = 1.0` and `dt = 0.5`. The remaining discretisation error is purely angular
(`docs/NATURE_MODEL.md#4`).

---

## D-015 — Length-to-breadth exponent raised to 1.5
**Date:** 2026-09-19 · **Status:** accepted, supersedes the coefficients in D-003

`LB = 1 + c_lb · φ^p_lb` with `c_lb = 0.14`, `p_lb = 1.5`, replacing
`c_lb = 0.50`, `p_lb = 0.80`.

*Why:* the eccentricity behaves like `sqrt(2·c_lb·φ^p_lb)` near `φ = 0`, so an
exponent below 1 gives it an infinite slope at zero wind. The old coefficients
made the flank rate fall to 0.66·R0 at `U = 0.5 m/s`, and the **total burned
area fell with increasing wind** up to `U ≈ 2.2 m/s`. A sweep over low wind
speeds would then have shown bigger fires at lower wind — a result that looks
like a finding and is an artefact.

Found by `tests/test_spread_analytic.py::test_burned_area_increases_with_wind_speed`,
which is exactly the kind of thing that test exists for.

*Consequence:* burned area is monotone in wind speed apart from a 1.7% dip at
`U ≈ 0.16 m/s` (negligible, and now a documented feature rather than a
surprise). `LB` is 1.8 at 4 m/s, 3.0 at 6 m/s, 7.3 at 10 m/s. The coefficients
remain **synthetic and uncalibrated** (`docs/ASSUMPTIONS.md#C-02`).

---

## D-016 — 16-direction propagation stencil by default
**Date:** 2026-09-19 · **Status:** accepted, supersedes the 8-neighbour stencil of D-003

`nature.stencil_max_offset` selects 8, 16 or 32 propagation directions
(offsets up to 1, 2 or 3 cells, primitive only). The default is **2**, i.e. 16
directions.

*Why:* with 8 directions the burned area was **non-monotone in wind speed** —
it peaked around 4 m/s and then fell, because an elongated ellipse has to be
approximated by a staircase of moves whose rates differ by more than an order of
magnitude. A sweep over wind would have produced smaller fires at higher wind:
an artefact indistinguishable, from the outside, from a result. The measured
area ratios against the analytic ellipse are in `docs/VALIDATION.md#4`.

*Cost:* about 1.7× the generation time of 8 directions; 32 directions costs
about 3.5×.

*Barriers are preserved.* A multi-cell move is blocked unless **every** cell its
segment touches is burnable, corner crossings included, so a one-cell-wide
non-burnable line stops the fire under any stencil (`spread.intermediate_offsets`).
This also makes a diagonal move require both of its adjacent orthogonal cells,
which is a deliberate strengthening: a one-cell diagonal barrier is now
impermeable too.

*Together with D-015:* `c_lb` was lowered again, to 0.07, so that the ellipse
stays inside the raster's competence over the whole sweep range. `LB` is 1.4 at
4 m/s, 2.0 at 6 m/s and 2.9 at 8 m/s.
