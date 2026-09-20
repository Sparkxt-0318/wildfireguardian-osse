# PROTOCOL — Forecast-Value Minimum Viable Experiment (MVE)

**Status:** frozen at protocol-freeze commit (recorded in every run manifest).
**Owner role:** Agent A (Model Auditor). Changes require a `docs/DECISIONS.md`
entry and a protocol version bump.
**Protocol version:** `mve-1.1.0`

> Synthetic nature model for controlled experiments; not an operational
> wildfire forecast model. Every result under this protocol is a statement
> about the declared OSSE, not about Korean wildfires (`docs/SCOPE.md`,
> §14 below).

---

## 1. Question

> How accurate and how timely must a wildfire forecast be before
> forecast-aware protective action outperforms a strong tuned trigger/buffer
> policy under hidden ground truth?

The scientific object is the **break-even set** `{θ : ΔJ(θ) = 0}` where
`ΔJ(θ) = J_forecast-aware(θ) − J_baseline`. The set is **not assumed** to be
monotone, connected, single-valued, convex, or to exist at all (§11).

This experiment is **not** the main WildfireGuardian empirical stress test. No
forecast, prediction or parameter from the main repository enters this one; the
nature world is independent by construction (`docs/DECISIONS.md#d-001`).

## 2. Pipeline and the separation it enforces

```text
NATURE WORLD          hidden truth: arrival-time field, true weather, spotting
    |
OBSERVATION PROCESS   cadence, latency, geolocation error, detection, outage
    |
AVAILABLE DATA D_s    exactly the records with availability_time_min <= s
    |
PLANNER / FORECAST    consumes D_s only; issues a forecast with an issue time
    |
POLICY                baseline (no forecast) or forecast-aware
    |
ACTION / MISSION      an ordered protective action at a decision time
    |
HIDDEN-WORLD EVALUATION   mission replayed against the hidden arrival field
```

The planner may never access: the nature seed, future fire state, future
weather, future spotting, the final perimeter, future observations, or any
evaluator-only quantity.

**Enforced in code, not by convention** (`src/wildfireguardian_osse/planner/sandbox.py`):

* `SealedTruth` wraps `NatureTruth`. Inside a `planner_sandbox()` context every
  attribute access raises `TruthAccessViolation`. Planner and policy code runs
  only inside that context.
* `PlannerView.at(s)` is the only route to observations. It filters on
  `availability_time_min <= s` and asserts the result, so a record acquired
  early but processed late stays unavailable until its availability time.
* `Forecast` objects carry `provenance` and `issue_time_min`; the evaluator
  refuses a forecast whose `issue_time_min` exceeds the decision time.

See `reports/LEAKAGE_AUDIT.md` for the evidence, and §13 for the runtime
assertion list.

## 3. World definition and splits

**A world `ω` is** `(landscape archetype, terrain, fuels, ignition, weather
sequence, nature randomness)`. Village, residents, road network and routes are
**nested inside** a world and are *not* independent units. The independent unit
for any statistic is the world.

Six landscape archetypes:

| archetype | terrain | fuels | purpose |
|---|---|---|---|
| `plain_uniform` | flat | uniform | control geometry |
| `plain_patchy` | flat | patchy | fuel heterogeneity |
| `ridge_cross` | ridge across the village–destination axis | patchy | terrain channelling |
| `ridge_along` | ridge along the axis | patchy | upslope runs |
| `slope_uniform` | planar slope | uniform | pure slope effect |
| `slope_patchy` | planar slope | patchy | slope × fuel |

**Splits are by archetype**, so no geography appears in more than one split:

| split | archetypes | use |
|---|---|---|
| `development` | `plain_uniform`, `slope_uniform` | implementation and debugging |
| `validation` | `plain_patchy`, `ridge_along` | **all** baseline and policy tuning |
| `final` | `ridge_cross`, `slope_patchy` | evaluated **once**, after protocol freeze |

Tuning touches `validation` only. The `final` split must not be inspected
before freeze; a runtime assertion refuses to tune on it (§13).

## 4. Decision timeline

* Decision epochs `s ∈ {s_0, s_0 + Δ, …}` with `s_0 = 20 min`, `Δ = 10 min`,
  up to the horizon. A policy is evaluated at each epoch until it orders.
* At epoch `s` a policy sees `D_s` and, if forecast-aware, the newest forecast
  whose **availability time** is at or before `s`.
* Ordering at `t_order` starts the mission after a fixed mobilisation delay.
* A policy that never orders is recorded as `NOT_ORDERED` and evaluated on
  whether the village was reached by fire.

### Act-now versus wait (§13 of the task brief)

Two explicit semantics, both implemented, with `ACT_NOW` primary:

* **`ACT_NOW`** — the policy acts at the epoch its trigger fires, using the
  newest forecast already available. Forecast latency therefore appears as
  **staleness**: at epoch `s` the usable forecast was issued at `s − δ`.
* **`WAIT_FOR_FORECAST`** — when the trigger fires, the policy does not act; it
  waits for the next forecast to arrive and re-evaluates then. **Waiting
  consumes real decision time and can destroy options**: the mission starts
  later, and the fire does not pause. Waiting is never free.

Later replanning (re-deciding after an order) is out of scope for the MVE.

## 5. Forecast

A `Forecast` records, always:

| field | meaning |
|---|---|
| `issue_time_min` | when it was produced |
| `availability_time_min` | when a policy may use it (`issue + latency`) |
| `valid_from_min`, `valid_to_min` | the interval it describes |
| `horizon_min` | `valid_to − issue` |
| `representation` | predicted **arrival-time raster**, minutes, `+inf` where not predicted to burn |
| `provenance` | `CONTROLLED_PERTURBATION` or `INDEPENDENT_MODEL_FORECAST` |
| `error_family` provenance class | `TOY_MECHANISM` / `STRESS_TEST` / `EMPIRICALLY_MOTIVATED` / `LEARNED` |

A **current-state estimate is not a forecast**. The independent model's output
is a forecast only because it propagates that estimate forward to valid times
strictly after the issue time; its skill is measured against truth over
`[valid_from, valid_to]` only.

Uncertainty representation in the MVE: **none** (a single deterministic arrival
raster). Recorded as a limitation, not smuggled in as a calibrated probability.

### Mode A — `CONTROLLED_PERTURBATION`

Takes the hidden arrival field and applies **structured** errors. It is a
*mechanism probe*, not a leakage-safe planner: it is derived from truth by
construction, which is exactly why it is labelled and why the flagship
conclusions lean on Mode B. At error 0 and latency 0 it is the **oracle
reference** — an upper bound, never an executable operational policy.

### Mode B — `INDEPENDENT_MODEL_FORECAST`

A structurally different, simplified model consuming `D_s` only:

* estimate the current fire from available detections (a weighted centroid and
  an extent, with false positives not labelled and therefore not filterable);
* estimate wind from available station observations (vector mean over a recent
  window), then **persist** it;
* grow a single ellipse from the estimated front at a fixed nominal rate.

It differs from nature in *structure*, not merely in parameters: nature uses a
16-direction raster front over heterogeneous fuel and terrain with a
time-varying wind and optional spotting; the planner model has no terrain, no
fuel map, no spotting, one wind, one rate, one ellipse. Flagship conclusions
rely on Mode B; Mode A remains for mechanism analysis.

## 6. Forecast degradation (Mode A) and error provenance

IID pixel noise is **not** used as a degradation family. Every family is
coherent and structured, and every one carries a provenance class:

| family | mechanism | provenance class |
|---|---|---|
| `direction_bias_deg` | rotate the predicted front about the estimated origin | `TOY_MECHANISM` |
| `spatial_shift_m` | coherent rigid translation of the predicted field | `TOY_MECHANISM` |
| `rate_bias` | multiplicative bias on predicted spread since issue time | `TOY_MECHANISM` |
| `latency_min` | forecast unavailable until `a = s + δ` | `STRESS_TEST` |
| `missed_spotting` | spot-seeded regions removed from the prediction | `STRESS_TEST` |

No error family is `EMPIRICALLY_MOTIVATED` or `LEARNED` in the MVE, because no
Korean or operational error statistics have been verified
(`docs/ASSUMPTIONS.md#D-08` is `UNKNOWN`).

**No probability distribution is placed over error regimes.** The experiment is
explicitly **conditional**: *under this error regime, the result is X.* Any
marginal "expected value of forecasting" would require an error likelihood this
repository does not have.

## 7. Missions, and the assisted-dispatch adapter

Each world contains a village, a responder base, a destination, and a road
network with routes between them.

`wildfireguardian-assisted-dispatch` is **not** available to this run, and its
full `base → resident → pickup → destination` logic is deliberately **not**
reimplemented here. Instead this repository declares an **adapter contract**
(`missions/dispatch.py::DispatchAdapter`) and ships a clearly-labelled minimal
placeholder, `PlaceholderDispatchAdapter`, which implements only:

* **full edge traversal interval** — an edge is passable only if the fire does
  not reach *any* cell of it during the whole interval the vehicle occupies it,
  not merely at entry;
* **pickup duration** — a dwell at the village during which the fire may arrive;
* **coherent scenarios** — one hidden world drives every leg of every mission.

These three are enough to produce **non-monotone feasible dispatch windows**
(waiting can reopen a window the fire briefly closed, and close one that was
open), which is the property the experiment depends on. Everything else in the
real package — fleet logic, resident heterogeneity, multi-stop routing — is
**not** modelled and is listed in `reports/LIMITATIONS.md`. When the package
becomes available it replaces the placeholder through the adapter, with no
change to the policies or the loss.

### Self-evacuation and assisted evacuation

These are **separate capabilities**, evaluated in parallel. The inference
"no self-evacuation route ⟹ rescue required" is **never** made. Outcome states:

```text
SELF_EVACUATION_FEASIBLE
ASSISTANCE_FEASIBLE
BOTH_FEASIBLE
ROUTE_EVIDENCE_UNRESOLVED     (planner-side only; truth is never unresolved)
NO_FEASIBLE_MISSION_FOUND
```

The word "safe" is not used anywhere in the outputs.

### Resource constraints

The MVE uses **independent single-mission feasibility**, explicitly labelled.
It is **not** a fleet-constrained population outcome and the result is never
called a "system protection rate". Finite responder resources must be modelled
before any population-level policy claim (`reports/LIMITATIONS.md`).

## 8. Loss function

Declared **before** the final run. No mortality, no lives-saved term.

```text
J(a, ω) = 1.00 · mission_failed
        + 0.50 · unnecessary_action
        + 0.30 · excess_lead_hours
        + 0.01 · responder_exposure_min
        + 0.001 · travel_time_min
```

| term | definition (evaluated against hidden truth) |
|---|---|
| `mission_failed` | the ordered mission did not complete, **or** no action was ordered and the fire reached the village by the horizon |
| `unnecessary_action` | an action was ordered although the fire never came within the threat radius of the village within the horizon |
| `excess_lead_hours` | hours between the action time and the actual threat time, beyond a 30-minute allowance; 0 when never threatened (that case is charged as `unnecessary_action` instead) |
| `responder_exposure_min` | responder minutes spent within the exposure radius of actively burning cells |
| `travel_time_min` | total mission travel time |

Failure dominates; the remaining terms create the cost of acting too early, so
a buffer that always evacuates is penalised and the trade-off the experiment
studies is real. Weights are a **declared modelling choice**, version-stamped
as `loss_version` in every record. Sensitivity to them is future work.

**Weight revision, declared.** The first weights tried (`0.20` / `0.05`) were
measured on the *development* split and found degenerate: evacuating four hours
early cost ≈ 0.06 against a failure cost of 1.0, so "always order at the first
epoch" was near-optimal and the tuned baseline came within 0.01 of the oracle.
A design in which the baseline already matches the oracle cannot discriminate
between forecasts and cannot express the `CRUDE_BUT_TIMELY` benchmark, so it
cannot answer the research question. The weights were rebalanced **once**, on
the stated argument that a four-hour-premature evacuation is about as costly as
one failed mission — not on any observed `ΔJ`, and never iterated toward a
preferred sign. `loss_version` moved to `mve-loss-1.1.0`
(`docs/DECISIONS.md#d-017`).

## 9. Policies

### Primary baseline — tuned trigger/buffer (`baseline_tuned_buffer`)

Deliberately strong, and tuned only on the `validation` split:

1. estimate the current fire front from `D_s` (the same detection-based
   estimator the independent model uses — the baseline is not handicapped);
2. order when the estimated fire is within a **spatial buffer** `B` of the
   village, **or** within a **time buffer** `T` of any edge of the planned
   route, where the time buffer uses a wind-conditioned persistence distance;
3. otherwise wait for the next epoch.

Tuning is a grid search over `(B, T, wind_gain)` minimising mean `J` on the
validation split. Tuned values are frozen into `config/` and reused unchanged.

### Secondary baselines

`baseline_fixed_buffer` (spatial only), `baseline_wind_conditioned`,
`baseline_fire_blind` (act at a fixed time regardless of observations), and
`oracle_reference` (perfect knowledge of the arrival field; **not** an
executable operational policy, reported only as a bound).

### Primary forecast-aware policy (`forecast_aware_feasibility`)

One policy, fixed semantics across every error sweep:

1. receive `D_s`;
2. obtain the newest available forecast (issued at `s − δ`);
3. assess mission feasibility **under the forecast** for acting now versus after
   a **safety margin** `m`;
4. order when acting now is feasible and waiting `m` longer is predicted not to
   be;
5. waiting is permitted only under the `WAIT_FOR_FORECAST` semantics (§4).

Fifteen variants are not compared. Policy semantics are held fixed while `θ`
sweeps, which is what makes `ΔJ(θ)` interpretable.

**The safety margin is tuned, on validation, and then frozen — like the
baseline buffer.** Tuning the baseline while leaving the forecast-aware policy
at an arbitrary setting would be an asymmetry in the baseline's favour, and the
protocol asks for a fair comparison rather than a flattering one. The margin is
chosen over the *whole condition grid at once*, never per condition: a policy
cannot know which error regime it faces.

Measured on validation (12 worlds): mean `J` falls monotonically from 0.425 at
`m = 0` to a plateau of ≈0.284 at and beyond the 90-minute forecast horizon
(90 → 0.2840, 105 → 0.2849, 120 → 0.2824, 150 → 0.2848). The smallest margin on
the plateau, **`m = 90 min`**, is frozen. The shape is itself a result: in this
OSSE the value of a forecast comes from using it as a full-horizon early-warning
test, not from shaving the decision to the last feasible moment — which is the
most error-sensitive point available.

**Declared policy-design sensitivity probe.** The aggressive variant `m = 0` is
run alongside, recorded under the separate policy id
`forecast_aware_margin_0`. It is **not** a competing primary policy; it exists
because it is the only setting under which this apparatus exhibits
`FORECAST_HARM`, and a benchmark suite that could not express harm would not be
validating anything. Which phenomena the *frozen* policy exhibits is reported
separately from which the *apparatus* can express.

## 10. Experimental grid (Stage A/B)

Two dimensions, per the brief's instruction to finish a 2-D experiment rather
than start a 6-D one:

```text
spatial/direction error:  none | low | medium | high | severe
forecast latency (min):   0 | 5 | 15 | 30 | 60
```

The error levels combine a directional bias and a coherent spatial shift, which
is the pair the implementation already supports coherently:

| level | direction bias | spatial shift |
|---|---|---|
| `none` | 0° | 0 m |
| `low` | 10° | 150 m |
| `medium` | 25° | 350 m |
| `high` | 45° | 700 m |
| `severe` | 80° | 1200 m |

Values are scaled to this simulation's timescale (180-min horizon, 4.8 km
domain, fires of order 1 km), **not** copied from the brief's illustrative
numbers. `rate_bias` and `missed_spotting` are implemented and exercised in the
benchmark suite, but are held fixed in the 2-D sweep and are the first
dimensions to add afterwards.

## 11. Break-even frontier

For each latency `δ`, `ΔJ(e, δ)` is examined across the error axis and every
sign change is recorded. The estimator reports one of:

```text
CROSSING        exactly one sign change, with the bracketing error levels
MULTIPLE_CROSSINGS   more than one
NO_CROSSING     ΔJ has one sign across the whole axis (direction recorded)
UNRESOLVED      the paired contrast is not separable from Monte-Carlo noise
```

No smooth curve is fitted through unsupported regions, and nothing is
interpolated across an `UNRESOLVED` band. `UNRESOLVED` is decided by a
lightweight paired diagnostic (paired mean ± 2 standard errors straddling zero)
— a **diagnostic, not formal inference**.

## 12. Handoff to `wildfireguardian-evaluation`

This repository owns **experiment generation**; `wildfireguardian-evaluation`
owns formal inference. World bootstrap, TOST, equivalence testing, multiplicity
correction and final confidence intervals are **not** implemented here.

One row per `(world, policy, condition, mode)` is exported to
`raw_outputs/evaluation_records.csv` with the columns the brief specifies:
`world_id`, `event_id`, `policy_id`, `error_regime`, `latency_min`, the
forecast-skill metrics, `loss`, `mission_success`, `travel_time_min`,
`resource_use`, `responder_exposure_min`, `failure_reason`, plus the full
provenance block (split, archetype, seeds, versions, config hash).

## 13. Runtime assertions

All fail loudly; none is a warning.

1. Planner/policy code cannot touch truth (`TruthAccessViolation`).
2. Every observation used satisfies `availability_time_min <= s`.
3. Every forecast used satisfies `availability_time_min <= s`.
4. Paired design: baseline and forecast-aware policies are evaluated against
   the identical hidden world object (world fingerprint compared).
5. Forecast latency is applied: a forecast's availability exceeds its issue
   time by exactly the configured latency.
6. Hidden scenario identity is inaccessible to the planner (no seed reaches the
   planner view).
7. The `final` split is refused to any tuning entry point.
8. Every exported row carries its full provenance block.

## 14. Claim discipline

Permitted under this protocol:

* *Under this declared OSSE, forecast-aware action outperformed / did not
  outperform the tuned baseline in the specified error–latency regimes.*
* *Conventional forecast skill was / was not sufficient to explain decision
  value across these worlds.*
* *Break-even regions were monotone / non-monotone / absent under this
  experiment.*

Forbidden until Korean anchoring and external validation exist:

* any statement of the form "Korean wildfire forecasts require X degrees or
  Y minutes";
* "these thresholds are operational requirements";
* "this system saves lives".

Negative results are reported as results. Worlds are **never** rejected because
the forecast-aware policy lost, because skill correlated with value, because
the frontier was uninteresting, or because the baseline dominated.

## 15. Staging

| stage | worlds | purpose |
|---|---|---|
| A | 12 | debug semantics; verify the pipeline end to end |
| B | 60 | estimate variance and runtime; first frontier |
| C | larger held-out study | only after Monte-Carlo variance is checked |

Stage C is scoped but not run here; `reports/MVE_READINESS.md` states what it
needs.

## 16. Constructed benchmark validation

Before any large run the OSSE must reproduce five qualitative benchmarks
(`experiment/benchmarks.py`). These are **validation cases, not evidence about
prevalence**: they show the apparatus can express each phenomenon, not that any
of them is common.

`ACCURATE_BUT_LATE`, `CRUDE_BUT_TIMELY`, `FORECAST_HARM`, `BASELINE_MATCH`,
`SIMILAR_SKILL_DIFFERENT_VALUE`.

## 17. Manifest

Every run records: `experiment_id`, `protocol_version`, `git_commit`,
`world_generator_version`, `nature_model_version`, `planner_model_version`,
`observation_model_version`, `baseline_version`, `policy_version`,
`loss_version`, `seed_manifest`, `data_hashes`, `config_hash`.
