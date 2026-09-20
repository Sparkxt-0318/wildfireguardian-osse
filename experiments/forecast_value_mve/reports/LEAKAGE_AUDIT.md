# LEAKAGE_AUDIT — proof that the planner did not see hidden truth

> Synthetic OSSE experiment. Nothing here is Korean-anchored.

This report answers one question: **can hidden truth reach the planner?** It is
written as an attack, in the spirit of `AGENTS.md` Agent C, and it states the
one place where truth *does* reach a forecast on purpose.

## 1. The boundary, and the one gate through it

Every planner and every policy in `wildfireguardian_fv` takes an
`InformationSet` and nothing else. There is exactly one function that turns a
world into an `InformationSet`:

```python
info.build_information_set(world, s)   # ~40 lines, auditable in full
```

It emits only:

| field | source | why it is legitimate |
|---|---|---|
| `fire_detections`, `fire_scan_log`, `weather_observations` | the laboratory's planner-visible tables, filtered by `available_at(s)` | the observation process is the whole point of an OSSE |
| `station_metadata` | station identifiers and positions | legitimately known before an incident |
| `published_specs` | *nominal* sensor specifications | the realised parameters stay hidden |
| `static_context` | elevation, coarse fuel class | published as static context by the laboratory, `docs/DECISIONS.md#d-006` |
| `village` | roads, houses, base, destinations | a dispatcher knows the road network |
| `grid_meta`, `horizon_min` | domain geometry and the decision window | properties of the exercise, not of the fire |

It does **not** emit: the arrival-time field, the burned mask, the continuous
fuel multiplier, the true weather series, the ignition point, spot events, the
detection ledger (which detections were spurious), sensor down-intervals, any
nature parameter, or any seed.

## 2. Four independent enforcement layers

**(a) Structure.** `InformationSet` is a frozen dataclass holding numpy arrays
and plain dicts. It holds no reference to `ExperimentWorld` or `NatureTruth`,
so there is no attribute path from planner code to truth.
`tests/fv/test_information_set.py::test_information_set_cannot_reach_hidden_truth`
walks the entire reachable object graph of a built information set and fails if
any laboratory truth object appears in it.

**(b) Construction-time audit.** Every build is audited and raises
`LeakageError` on any finding:

* no record with `availability_time_min > s` (re-checked after filtering);
* no field name matching a forbidden pattern (`arrival_time_min`,
  `burned_mask`, `seed`, `nature_param`, `is_spurious`, `ignition`, ... );
* no integer or embedded string equal to any of the world's eleven seed values
  (five experiment streams, six laboratory streams, plus the master seed).

Both detectors are themselves tested by injecting a violation and requiring
that the audit catches it — a leakage detector that has never fired is not
evidence of anything.

**(c) Execution-time guard.** `info.truth_access_guard()` wraps every call into
policy code in `run_policy`. Inside it, `numpy.load` and `open` raise
`LeakageError` for any path containing a `truth` component. This is a backstop
for the single thing structure cannot prevent: planner code that opens the
world directory itself.

**(d) Import-graph separation.** `tests/fv/test_package_separation.py` parses
every module of `wildfireguardian_osse` and fails if any of them imports
`wildfireguardian_fv`. The dependency is one-way
(`docs/DECISIONS.md#d-017`).

## 3. Specific attacks and their results

| attack | result |
|---|---|
| Reach `NatureTruth` or `ExperimentWorld` from `D_s` by attribute or container walk | **no path exists** |
| Use an observation acquired before `s` but delivered after `s` | **withheld**; a dedicated test picks a time between an early detection's event and its availability and asserts `D_s` is empty |
| Recover the world's identity from an exposed seed | **no seed value appears**; audited numerically and as substrings |
| Have a planner open `truth/arrival_time_min.npy` | **raises** under the guard |
| Learn the future by extending the simulated horizon | **prefix-causal**: a world simulated to 300 min yields a byte-identical `D_s` at `s = 90` to one simulated to 180 min |
| Let an observation-side seed change the hidden fire | **impossible by namespace**: `wgosse|v1` and `wgfv|v1` are disjoint, and the laboratory's own `test_stream_independence` covers its five streams |
| Let the experiment's village layout perturb the fire | **impossible**: the village is drawn from `wgfv|v1`, the fire from `wgosse|v1`; the village is also built *before* the ignition is placed, never after |
| Give the forecast-aware policy a plan the baseline could not have made | **both policies share one decision loop, one adapter and one world object**; a runtime assertion requires identical hidden arrival times per resident across the pair |
| Tune on the worlds used for the final reading | **raises**: the final split is locked outside `final_split_unlocked`, and tuning asserts its worlds are validation-split |

## 4. The one place truth is used on purpose

**Mode A (`CONTROLLED_PERTURBATION`) is built from hidden truth. It is not
leakage-safe, and it is not meant to be.**

Mode A takes the hidden arrival-time field, coarsens it, and applies a named
degradation (rotation about the true ignition point, rate scaling, translation,
spot removal). That is what makes it useful: the error is *exactly* the declared
magnitude and nothing else, which is what lets the response surface be
attributed to one error family.

Consequences, enforced:

* every Mode A forecast carries `mode="CONTROLLED_PERTURBATION"` and the
  provenance string `CONTROLLED_PERTURBATION`, in the forecast object and in
  every exported row;
* the closure that hands Mode A to a policy is confined to one function
  (`runner.make_forecast_source`) and is the only place in the package where a
  policy's input depends on truth;
* **no Mode A number is evidence about what a real planner could achieve.**
  Flagship conclusions rest on Mode B.

A reader who wants only leakage-safe results should filter the exported rows to
`forecast_mode ∈ {NONE, INDEPENDENT_MODEL_FORECAST}`.

The oracle reference is the same kind of object and is labelled harder still:
its policy id is `oracle_reference::NOT_OPERATIONAL::v1`.

## 5. Two honest residuals

**(a) The ignition distribution is conditioned on the village.** Ignitions are
placed upwind of the village centre at 1400–3000 m, with a ±70° bearing jitter.
A planner that knew the generation rule would therefore hold a prior over where
fires start relative to the houses.

This is *distributional* context, not per-world information: it is identical for
both policies, it cannot distinguish one world from another, and neither policy
uses a prior of any kind — both act on detections. It is recorded here rather
than hidden because it is the kind of thing that could become leakage if a
future planner learned a prior from the generator. It is declared in
`PROTOCOL.md §10` and in `worlds.GENERATION_AUDIT`.

**(b) Static context narrows the future by an unmeasured amount.** Terrain and
coarse fuel class are planner-visible by `docs/DECISIONS.md#d-006`. Combined
with a detection, how much do they narrow the fire's future? Believed small —
ignition, wind and the spread coefficients are all hidden — but *believed, not
measured*. This is the laboratory's own open question
(`tasks/CURRENT.md`), inherited unchanged. Mode B uses fuel class only through
its own miscalibrated mapping and ignores terrain entirely
(`docs/DECISIONS.md#d-019`), which bounds how much of this channel the current
planner could be exploiting — but does not bound it for a future one.

## 6. Verdict

Within the mechanisms listed above, **no path exists by which hidden truth,
a hidden parameter, or future information reaches a Mode B forecast or either
policy.** Mode A is built from truth by design and is labelled as such
everywhere it appears. The two residuals in §5 are declared, bounded in
argument, and unmeasured in magnitude; §5(b) in particular should be quantified
before any claim that depends on the planner's blindness being complete.
