# PROTOCOL — forecast-value minimum viable experiment (MVE)

**Status: frozen (freeze 3, 2026-09-20).** Everything below was fixed before the
final split was read. The freeze history is in §18; after freeze 3, changes are
recorded in `reports/MVE_RESULTS.md` as protocol deviations, never by editing
this file in place.

> **Synthetic OSSE experiment.** No Korean DEM, fuel map, road network, village
> archetype or weather regime constrains any world here. Nothing in this
> experiment may be stated as a requirement for Korean wildfire operations
> (§16).

---

## 1. The question

> How accurate, and how timely, must a wildfire forecast be before
> forecast-aware protective action outperforms a strong tuned trigger/buffer
> policy under hidden ground truth?

Formally, estimate the response surfaces `J_baseline(θ)` and
`J_forecast(θ)` and the break-even set `{θ : ΔJ(θ) = 0}`, where
`ΔJ = J_forecast − J_baseline`. The break-even set is **not** assumed to
exist, to be connected, to be single-valued or to be monotone (§10).

This is not the main WildfireGuardian empirical stress test and is not
compared against it in this run (§17).

## 2. Architecture and the hidden-variable boundary

```
NATURE WORLD              wildfireguardian_osse.nature     (hidden)
    ↓
OBSERVATION PROCESS       wildfireguardian_osse.observations
    ↓
AVAILABLE DATA D_s        wildfireguardian_fv.info.build_information_set
    ↓
PLANNER / FORECAST        wildfireguardian_fv.planner
    ↓
POLICY                    wildfireguardian_fv.policy
    ↓
ACTION / MISSION          wildfireguardian_fv.dispatch
    ↓
HIDDEN-WORLD EVALUATION   wildfireguardian_fv.policy.base.run_policy
```

The planner may never access: the nature seed, any future fire state, any
future weather, any future spotting, the final perimeter, any observation not
yet available, or any evaluator-only quantity.

Enforced structurally, not by convention:

| mechanism | where |
|---|---|
| `InformationSet` holds arrays and dicts only; no reference to the world | `info.py` |
| the gate re-audits availability, seed values and field names on every build | `info.build_information_set` |
| reading a `truth/` artefact raises while policy code runs | `info.truth_access_guard` |
| the object graph of `D_s` is walked in tests and must contain no truth object | `tests/fv/test_information_set.py` |
| the laboratory package must not import the experiment package | `tests/fv/test_package_separation.py` |

The one deliberate exception is Mode A (§5), which is evaluator-side and
labelled as such in every record it produces.

## 3. Worlds, splits and seeds

**World** = (landscape, ignition, weather sequence, nature randomness, village
layout). Residents and routes are **nested** inside a world and are not
independent replicates. `N` always means worlds, never resident-outcomes.

**Splits by landscape archetype**, so no geography is shared between tuning
and the final reading:

| split | archetypes | use |
|---|---|---|
| development | `open_plain`, `rolling_noise` | implementation, benchmarks |
| validation | `sloped_valley`, `mosaic_barrier` | **all** tuning |
| final | `ridge_channel`, `plateau_step` | one frozen-protocol pass |

`splits.note_final_split_read` raises unless inside
`splits.final_split_unlocked`, so an accidental early read fails loudly. The
number of final-split reads is written into the stage manifest.

**Seed separation.** Two disjoint hash namespaces:

* `wgosse|v1` — nature, weather, spotting, sensor, missingness (laboratory);
* `wgfv|v1` — world layout, ignition placement, resident capability,
  perturbation, policy (experiment).

Re-rolling the village cannot move the fire, and re-rolling the fire cannot
move the village. Seeds are persisted in each world's manifest entry and are
never exposed to a planner.

## 4. Forecast

### 4.1 Product definition
Issue time `s`; valid window `[s, min(s+90, horizon)]`; representation
`ARRIVAL_TIME_FIELD_COARSE` on a 120 m decision grid (nature runs at 30 m);
uncertainty field present in the schema, `None` in v1. A product whose valid
window starts before its issue time is refused at construction: a current-state
estimate is not a forecast.

### 4.2 Cadence and latency
Issued every 15 minutes. Usable only at `availability = s + δ`. A forecast
issued 40 minutes ago with `δ = 60` is still unusable.

### 4.3 Act-now versus wait
`ACT_NOW`, `WAIT_FOR_FORECAST`, `NO_ACTION`. Decisions every 5 minutes.
Waiting consumes real decision time: the loop advances, the hidden fire grows,
and routes close. One commitment per resident; no replanning after dispatch
(recorded as a limitation, not an oversight).

### 4.4 Fixed semantics
Policy semantics are identical in every error regime. Only the forecast handed
to the policy changes.

## 5. Two forecast-generation modes

| | Mode A | Mode B |
|---|---|---|
| label | `CONTROLLED_PERTURBATION` | `INDEPENDENT_MODEL_FORECAST` |
| built from | hidden truth, degraded in a named way | `D_s` only |
| error | exactly the declared magnitude | emergent, nobody chose it |
| leakage-safe | **no, by construction** | yes |
| role | mechanism probe | flagship evidence |

Mode B is a structurally different model: it fits one growing ellipse to the
observed detections and extrapolates. Declared structural blind spots — no
terrain, no fuel heterogeneity beyond the published coarse class (mapped by its
own rule), no spotting — and a rate law that is additive-linear in wind speed
where nature is multiplicative in a power of it. Neither its form nor its
coefficients were fitted to nature.

## 6. Mission semantics and outcome vocabulary

`wildfireguardian-assisted-dispatch` is the intended source of these semantics.
It is not importable in this run, so `dispatch.py` defines the **adapter
contract** (`MissionFeasibilityAdapter`) and ships a temporary internal
implementation labelled `INTERNAL_PLACEHOLDER_V1` in every record. The
placeholder carries only: the `base → resident → destination` shape, full
edge-traversal-interval hazard semantics, an explicit pickup duration, and one
hazard field driving both belief-side and truth-side evaluation.

Outcome states: `SELF_EVACUATION_FEASIBLE`, `ASSISTANCE_FEASIBLE`,
`BOTH_FEASIBLE`, `ROUTE_EVIDENCE_UNRESOLVED`, `NO_FEASIBLE_MISSION_FOUND`.
The word "safe" is not used. Self-evacuation capability is an assumption about
people and is **never** inferred from route existence, nor route existence from
capability; the two are evaluated in parallel.

## 7. Error families and their provenance

| family | provenance | swept in the MVE |
|---|---|---|
| `direction_bias_deg` | `STRESS_TEST` | yes |
| `latency_min` | `TOY_MECHANISM` | yes |
| `rate_bias_factor` | `STRESS_TEST` | no (next) |
| `displacement_m` | `STRESS_TEST` | no (next) |
| `missed_spotting` | `TOY_MECHANISM` | no (next; Mode B has it structurally) |

**No family is `EMPIRICALLY_MOTIVATED` or `LEARNED`.** No probability
distribution is placed over θ. Every result is therefore a conditional
statement — "under this error regime, X" — and is written that way.
IID pixel noise is not offered as a degradation at all.

## 8. Random streams

`world_layout_seed`, `ignition_seed`, `resident_seed`, `perturbation_seed`,
`policy_seed`, each with sub-streams. A quantity whose number of draws can vary
gets its own sub-stream.

## 9. Manifest

Every run records: `experiment_id`, `git_commit` (and dirty flag),
`world_generator_version`, `nature_model_version`, `planner_model_version`,
`observation_model_version`, `baseline_version`, `policy_version`,
`loss_version`, `dispatch_adapter_version`, `seed_manifest`, `data_hashes`,
`config_hash`, and the per-world generation audit.

## 10. World-generation rules (predeclared)

Fixed before any result was inspected. A world is **never** rejected because the
forecast-aware policy loses in it, because the frontier is dull, or because the
baseline dominates. The only rejection rule is mechanical: a world the
laboratory flags as discretisation-unsound is regenerated at the next index.

Every distribution is classified `DATA-INFORMED` / `ASSUMED` / `STRESS-TEST` in
`worlds.GENERATION_AUDIT` and reproduced in `reports/MVE_METHOD.md`.
**None is `DATA-INFORMED` in this run.**

## 11. Baseline

Primary: a **tuned** trigger/buffer policy — observed fire state, plus a buffer
conditioned on observed wind and on how stale the last scan is, plus a declared
route rule. Trigger buffer and route buffer are free to differ; tuning chooses
both. Secondary: fixed buffer, fire-blind. Oracle: plans against hidden truth,
**not an executable operational policy**, reported only as a bound.

Tuning: validation worlds only, **144 configurations for the baseline and 120
for the forecast-aware policy**. An optimum landing on the edge of its search
range is recorded in the tuning artefact and quoted in the method report,
because an edge optimum usually means the policy was not actually optimised —
unless the leaderboard shows the parameter is flat, which is a finding rather
than a defect.

Both policies parameterise a **separate trigger buffer and routing buffer**.
One number doing both jobs is pulled in opposite directions — a generous
trigger wants a large radius, a usable road wants a small one — and tuning
resolves the conflict by shrinking it, which silently disables the trigger.
Giving that freedom to the baseline and not to the forecast-aware policy would
make the comparison a straw man rather than a test (§18, freeze 2).

The forecast-aware policy is tuned **once per forecast mode**, each at its own
undegraded condition, and is then held fixed across that mode's entire error
sweep — which is what §4.4 requires. Mode A and Mode B are different
experiments, and a policy tuned against a weak forecast learns to lean on its
observed-fire trigger and then cannot exploit a strong one (§18, freeze 3).

## 12. Runtime assertions

Failing loudly, every one of them:

1. the planner cannot reach hidden truth (structure + guard + object-graph walk);
2. no observation with `availability_time > s` is in `D_s`;
3. both policies run against the same world object, with identical hidden
   arrival times per resident;
4. forecast latency equals `availability − issue` exactly;
5. no seed value appears in a planner-facing object;
6. the final split cannot be read outside the frozen-protocol context;
7. every exported row carries complete provenance;
8. the baseline is verified θ-invariant rather than assumed to be.

## 13. Loss

```
J = 1.00·protection_failure
  + 0.25·unnecessary_dispatch
  + 0.15·responder_exposure_min/10
  + 0.05·travel_time_min/60
  + 0.05·resource_use
```

No mortality term and no "lives saved" term. World-level loss is the mean over
that world's residents. Feasibility is per mission, independent of every other
mission: `INDEPENDENT_SINGLE_MISSION_FEASIBILITY`. This is **not** a
fleet-constrained population outcome and must never be called a system
protection rate. Sensitivity to the weights is future work.

## 14. Grid and staging

θ-grid: `direction_bias_deg ∈ {0, 10, 20, 35, 55}` ×
`latency_min ∈ {0, 5, 15, 30, 60}` = 25 conditions, in both modes.
Values are chosen for this laboratory's timescale (240 min horizon, 15 min
sensor cadence, ~30 min missions), not copied from an operational setting.

| stage | split | worlds | purpose |
|---|---|---|---|
| A | development | 12 | debug semantics |
| B | validation | 60 | variance and runtime |
| C | final | 60 | one frozen-protocol pass |

## 15. Handoff

This repository owns experiment generation. `wildfireguardian-evaluation` owns
formal inference: world bootstrap, TOST, equivalence, multiplicity correction,
final confidence intervals. The paired bootstrap here is a **lightweight
diagnostic only**, used to decide whether the experiment is looking at signal
or at Monte Carlo noise. Export contract: `records.OUTCOME_COLUMNS`.

## 16. Claim discipline

Allowed:
* "Under this declared OSSE, forecast-aware action did / did not outperform the
  tuned baseline in the specified error–latency regimes."
* "Conventional forecast skill was / was not sufficient to explain decision
  value across these worlds."
* "Break-even regions were monotone / non-monotone / unresolved under this
  experiment."

Forbidden:
* any statement of the form "Korean wildfire forecasts require X degrees or
  Y minutes";
* "these thresholds are operational requirements";
* "this system saves lives".

Negative results are reported as results. If the strong baseline dominates
almost everywhere, that is the finding. If the forecast-aware policy always
wins, the first move is to ask whether the baseline is under-tuned or the
nature/planner relationship is too favourable.

## 17. Out of scope for this run

No integration with the main WildfireGuardian repository. Comparison against
its empirical stress test comes later and must not be forced to agree:
disagreement would itself be a scientific result.

## 18. Freeze history

**Freeze 1 (superseded).** The forecast-aware policy had a single
`fallback_buffer_m` doing two jobs: dilating the observed fire for route
blocking, *and* deciding when a resident counted as already threatened. The
baseline, by contrast, had a trigger buffer and a routing buffer that tuning
could set independently.

Tuning resolved the forecast-aware policy's conflict by shrinking the shared
buffer to 150 m — good for routing, far too small to trigger on — and the
policy consequently acted on 16% of resident-decisions against the baseline's
71%. The asymmetry, not the forecast, was doing most of the work.

**Freeze 2 (superseded).** `ForecastAwareParams` was split into `route_buffer_m`
and `visible_threat_buffer_m`, the forecast search grid was widened from 40 to
120 configurations to cover both, and every stage was re-run from scratch.
Validation loss for the forecast-aware policy moved from 0.291 to 0.222 against
an unchanged baseline at 0.202.

The defect was found by reading **validation-split** failure compositions. **No
final-split artefact existed at the time**: the stage-C run in flight was
stopped before any of its output was read, and its files were never written.
The final split was therefore still read exactly once, after freeze 2.

One further amendment was made in the same window, to *analysis* rather than to
the experiment: the frontier classifier originally required the two sides of a
sign change to be **adjacent** grid points. A cell close to zero is exactly the
cell whose interval is most likely to cover zero, so that rule hid a crossing
precisely when the grid bracketed it well. Brackets are now sought between
consecutive **resolved** points and flagged when they span an unresolved cell.
This changes no loss and no decision — only how a surface is described.

**Freeze 3 (current).** Freeze 2 tuned the forecast-aware policy against Mode B
only and carried those parameters into Mode A. Mode B's forecast under-predicts
spread, so tuning against it selected a policy that leans on its 700 m
observed-fire trigger and barely consults the forecast at all — the `lead_min`
leaderboard was exactly flat across 30, 60 and 90 minutes. Running Mode A under
those parameters then measured *that* policy, not the value of an accurate
forecast, and would have confounded "an accurate forecast is not worth acting
on" with "this policy was set up not to act on one".

The forecast-aware policy is now tuned **once per forecast mode**, each at its
own undegraded condition, and held fixed across that mode's whole error sweep.
The baseline is unchanged and is still θ-invariant, so the pairing is unchanged.

Again, **no final-split artefact existed when the defect was found**: the
stage-C run in flight was stopped and its files deleted before any of its
output was read. The final split is read exactly once, after freeze 3.
