# MVE_METHOD — exact design of the forecast-value minimum viable experiment

> **Synthetic OSSE experiment.** Generic synthetic worlds. No Korean DEM, fuel
> map, road network, village archetype or weather regime constrains anything
> here, and no statement below is a requirement for Korean wildfire operations.

The frozen protocol is `../PROTOCOL.md`. This report is the *implementation*
record: what was actually built, with the numbers that were used.

---

## 1. The chain, module by module

```
NATURE WORLD           wildfireguardian_osse.nature.world.simulate_nature
    ↓                  30 m cells, 192×192 (5.76 km), 240 min at 1 min steps
OBSERVATION PROCESS    wildfireguardian_osse.observations.process
    ↓                  fire sensor: 375 m pixels, 15 min cadence, p_detect 0.90,
    ↓                  150 m geolocation sigma, 5+2 min latency + jitter;
    ↓                  weather network: 9 stations, 10 min cadence;
    ↓                  missingness: MCAR, p = 0.05
AVAILABLE DATA D_s     wildfireguardian_fv.info.build_information_set
    ↓                  the only gate; see LEAKAGE_AUDIT.md
PLANNER / FORECAST     wildfireguardian_fv.planner
    ↓                  Mode A (perturbed truth) and Mode B (independent model)
POLICY                 wildfireguardian_fv.policy
    ↓                  one shared decision loop, 5 min cadence
ACTION / MISSION       wildfireguardian_fv.dispatch  (INTERNAL_PLACEHOLDER_V1)
    ↓
HIDDEN-WORLD EVAL      wildfireguardian_fv.policy.base.run_policy
```

## 2. Worlds

**Unit.** One world = (landscape, ignition, weather sequence, nature
randomness, village layout). Six residents are nested inside each world; they
are not independent replicates, and `N` always counts worlds.

**Archetypes and splits.** Six landscape/fuel families, partitioned so that no
geography is shared between tuning and the final reading:

| archetype | terrain | fuels | split |
|---|---|---|---|
| `open_plain` | flat | patchy | development |
| `rolling_noise` | smooth noise, 120 m relief | patchy | development |
| `sloped_valley` | planar, 12° | patchy | validation |
| `mosaic_barrier` | smooth noise, 90 m relief | non-burnable band | validation |
| `ridge_channel` | ridge, 200 m relief | patchy | final |
| `plateau_step` | planar, 6° | partial-burn band | final |

**Village.** A perturbed 6×6 lattice road network (spine roads along the
centre row and column, 72% of minor edges retained, connectivity restored
deterministically), six houses within 900 m of the domain centre each on its
own driveway, a responder base at one corner and two destinations at the far
corners. Travel speeds: 700 / 400 / 200 m·min⁻¹ for spine / minor / driveway.

**Ignition.** Placed *after* the village, upwind of the village centre at
Uniform(1400, 3000) m with a Uniform(−70°, +70°) bearing jitter. A substantial
fraction of worlds therefore never threatens the village, which is what makes
"unnecessary dispatch" a measurable cost rather than a free label.

**Wind.** Uniform(2.5, 6.0) m·s⁻¹ — the upper bound is the laboratory's
validated stencil limit (`docs/VALIDATION.md#4`), not a meteorological claim —
direction Uniform(0, 360°), with a 35° to 85° shift in 35% of worlds at a time
in the middle third of the horizon. Spotting enabled in 40% of worlds.

**Rejection rule.** Purely mechanical: a world the laboratory flags with a
discretisation warning is regenerated at the next index. No world is ever
rejected for its result.

## 3. World-generation audit

Every distribution, with its provenance class (full text in
`worlds.GENERATION_AUDIT`, reproduced in each stage manifest):

| quantity | class |
|---|---|
| ignition location (distance, bearing) | `ASSUMED` |
| wind speed | `STRESS-TEST` |
| wind direction | `ASSUMED` |
| wind shift prevalence and magnitude | `STRESS-TEST` |
| fuel heterogeneity | `ASSUMED` |
| terrain | `ASSUMED` |
| spotting prevalence | `STRESS-TEST` |
| route topology | `ASSUMED` |
| village geometry | `ASSUMED` |
| resident self-evacuation capability | `ASSUMED` |

**None is `DATA-INFORMED`.** No world in this experiment may be described as
Korean, and none is.

## 4. The forecast product

Issued every 15 minutes from the information set at that time. Valid window
`[s, min(s+90, 240)]`. Representation: predicted fire arrival time on a 120 m
decision grid — four times coarser than nature. Uncertainty field is in the
schema and is `None` in v1. Usable only from `s + δ`.

A product whose valid window begins before its issue time is refused at
construction: a current-state estimate is not a forecast.

### Mode A — `CONTROLLED_PERTURBATION`
Hidden truth, coarsened by block-minimum, then: rotation by `e` about the true
ignition point, optional rate scaling, optional translation, optional removal
of spot-attributable area. Evaluator-side; see LEAKAGE_AUDIT.md §4.

### Mode B — `INDEPENDENT_MODEL_FORECAST`
Consumes `D_s` only:

1. group available detections by scan;
2. estimate the source as the centroid of the earliest available scan;
3. estimate heading from centroid motion between the first and latest scans,
   falling back to the observed wind when only one scan exists;
4. estimate the head rate from the advance of the leading edge along that
   heading, blended 0.6/0.4 with its own wind law
   `R = 2.6 + 1.6·U` m·min⁻¹ and clipped to a plausibility band;
5. shape one ellipse with `LB = 1 + 0.45·U`, focus at the estimated source;
6. project `τ̂(x) = t₀ + |x − x₀| / R(φ)` with
   `R(φ) = R_head(1−ε)/(1 − ε cos φ)`;
7. scale the rate by a coarse fuel-class factor of its own devising.

**Structural mismatch, by design** (`docs/DECISIONS.md#d-019`):

| | nature | Mode B planner |
|---|---|---|
| propagation | travel-time accumulation over a heterogeneous ROS raster, 16-direction stencil | one analytic ellipse from an estimated source |
| wind law | `R₀(1 + 0.40·U^1.5)`, multiplicative | `2.6 + 1.6·U`, additive-linear |
| length-to-breadth | `1 + 0.07·U^1.5` | `1 + 0.45·U` |
| slope | yes | **none** |
| fuel | continuous hidden multiplier | coarse published class, own mapping |
| spotting | stochastic, optional | **none** |
| wind in time | AR(1) plus scheduled shifts | last 30 min of station observations, held constant |

At the wind speeds swept here the planner's head rate is slower than nature's
(9–10 versus 12–13 m·min⁻¹ at 4 m·s⁻¹), so Mode B under-predicts spread. That
bias is *emergent* — nobody set it — and it is measured in
`FRONTIER_RESULTS.md` rather than assumed.

## 5. Policies

Both run through **one** decision loop (`policy/base.py`), at a 5 minute
cadence, with one commitment per resident and no replanning. Only the belief
differs.

### Baseline — tuned trigger/buffer
Trigger buffer `B = b₀ + b₁·U_obs·(staleness + b₂)`; route buffer
`= route_buffer_frac · B`. The two must be free to differ: a routing buffer as
generous as the trigger buffer makes the policy trigger and then refuse to
move. A resident inside the trigger buffer is dispatched to, if a route exists
that clears the route buffer.

### Forecast-aware
Belief = observed fire (detection event times, dilated by `route_buffer_m`)
merged by element-wise minimum with the usable forecast. A resident is
threatened if the belief predicts arrival within `lead_min`, **or** if a
detection lies within `visible_threat_buffer_m` of the house. Act now if a
feasible mission exists under that belief; wait only while no forecast is
usable, no threat is already visible, and the next product is within
`max_wait_min`. Waiting consumes real decision time.

The trigger and routing buffers are separate parameters here for the same
reason they are in the baseline — see `../PROTOCOL.md` §18 for why the first
freeze got this wrong and what it cost.

Semantics are **identical in every error regime**; only the forecast changes.

### Secondary and reference
Fixed buffer; fire-blind (dispatch on first detection, no hazard avoidance);
oracle (`oracle_reference::NOT_OPERATIONAL::v1`, plans against hidden truth,
reported only as a bound).

## 6. Tuning

Validation worlds only (16 worlds), grid search, loss as declared.

| policy | configurations | chosen | validation `J` |
|---|---|---|---|
| baseline | 144 | `b₀ = 1000 m`, `b₁ = 0`, `b₂ = 10 min`, `route_buffer_frac = 0.15` | **0.2019** |
| forecast-aware | 120 | `lead = 30 min`, `route_buffer = 150 m`, `visible_threat_buffer = 700 m`, `allow_wait = False` | **0.2220** |

The baseline's optimum is interior in `b₀` (range 200–2000 m) and in
`route_buffer_frac` (range 0.05–0.60); the forecast-aware policy's is interior
in both of its buffers (50–600 m and 150–1400 m). Those are real optima, not
grid artefacts.

Two edge optima are recorded, and both are informative rather than defects:

* **`b₁ = 0`**, at the bottom of {0, 6, 12}. Wind-conditioning the buffer did
  not help; the response cannot usefully go below zero. The tuned baseline is a
  large *static* trigger buffer (1000 m) with a tight routing clearance
  (150 m): trigger early, route close.
* **`lead_min = 30`**, at the bottom of {30, 60, 90} — but the leaderboard's
  top five tie at 0.2220 across *all three* values. The lead threshold is
  exactly flat, which means the Mode B forecast essentially never fires the
  trigger before the 700 m observed-fire buffer already has. Widening the grid
  would change nothing; this is a statement about the planner, and it is
  picked up again in `FAILURE_ANALYSIS.md`.

The forecast-aware policy chose not to wait (`allow_wait = False`), and waiting
ties with not-waiting, so the act-now/wait axis is also flat in this world set.

Tuning is **per forecast mode**, each at its own undegraded condition and then
fixed across that mode's whole error sweep. Mode A and Mode B are different
experiments — a mechanism probe and a flagship — and a policy tuned against a
weak forecast learns to lean on its observed-fire trigger and cannot exploit a
strong one. `../PROTOCOL.md` §18 (freeze 3) records what carrying one mode's
parameters into the other cost, and why the numbers in the table above are for
Mode B.

## 7. Loss

```
J = 1.00·protection_failure + 0.25·unnecessary_dispatch
  + 0.15·responder_exposure_min/10 + 0.05·travel_time_min/60
  + 0.05·resource_use
```

`protection_failure` = the fire reached a resident within the horizon and no
assisted mission extracted them in time. **No mortality term.** World loss is
the mean over that world's six residents.

Feasibility is per mission, independent of every other mission
(`INDEPENDENT_SINGLE_MISSION_FEASIBILITY`). Finite responder fleets are not
modelled, so **no number here is a system or population protection rate**.

Self-evacuation is evaluated in parallel, at 250 m·min⁻¹, gated on a declared
capability — never inferred from route existence, and never inferring rescue
need from the absence of a route.

## 8. Skill

Scored against the hidden field over the forecast's own valid window, excluding
cells that had already burned at issue time (predicting the past is not skill):
CSI/IoU, POD, FAR, missed-event rate, front-displacement of the predicted
burned set, and signed/absolute arrival-time error. The skill module imports no
policy, no loss and no dispatch code — asserted against its executable source —
so "does skill predict value?" has content.

## 9. Error grid and staging

`direction_bias_deg ∈ {0, 10, 20, 35, 55}` × `latency_min ∈ {0, 5, 15, 30, 60}`,
both modes: 50 forecast conditions per world, plus the θ-invariant baseline.

| stage | split | worlds | rows | purpose |
|---|---|---|---|---|
| A | development | 12 | 3 672 | debug semantics |
| B | validation | 60 | 18 360 | variance and runtime |
| C | final | 60 | 18 360 | one frozen-protocol pass |

The baseline consumes no forecast, so its result is θ-invariant and is computed
once per world. That is verified rather than assumed
(`runner.assert_baseline_theta_invariance`, and a test that re-runs it under
six conditions requiring exact equality).

## 10. Reproduction

```bash
pip install -e '.[dev,figures]'
pytest -q                                   # 221 tests, includes tests/fv
wg-fv tune       --n-worlds 16              # validation split only
wg-fv benchmarks --n-worlds 12              # development split
wg-fv run A                                 # then B
wg-fv frontier A
wg-fv figures  A
wg-fv run C --freeze-ack                    # final split, once
```

Every stage writes a manifest recording the git commit and dirty flag, all
component versions, the seed manifest, the full per-world generation audit and
a SHA-256 of the row file. Rows are written as `outcomes_stage*.csv.gz`; the
recorded hash is of the **uncompressed** content, because gzip output is not
byte-stable across implementations and a manifest should verify the data rather
than the archive.
