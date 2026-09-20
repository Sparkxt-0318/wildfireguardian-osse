# MVE_READINESS

> Synthetic OSSE experiment. Not Korean-anchored.

The stop condition for this run (`PROTOCOL.md`): freeze the protocol, validate
separation, run the staged experiment, export evaluation records, produce a
preliminary frontier, and identify what Korean anchoring needs. All six are
done. This report answers the seven readiness questions directly, and says
where each answer is weak.

---

## 1. Is the experiment leakage-safe?

**Yes for Mode B, deliberately not for Mode A, and both are labelled.**

Four independent layers, detailed in `reports/LEAKAGE_AUDIT.md`:

1. **Structure.** `InformationSet` holds arrays and plain dicts, with no
   reference to the world. A test walks its whole reachable object graph and
   fails if any laboratory truth object appears.
2. **Construction audit.** Every build re-checks availability, forbidden field
   names and all eleven seed values, and raises `LeakageError`. Both detectors
   are themselves tested by injecting a violation — a leakage detector that has
   never fired is not evidence of anything.
3. **Execution guard.** Reading a `truth/` artefact raises while policy code
   runs.
4. **Import graph.** The laboratory package must not import the experiment
   package, asserted by parsing every laboratory module.

Prefix causality is preserved through the gate: a world simulated to 300
minutes yields an identical `D_s` at `s = 90` to one simulated to 180.

**Mode A is built from hidden truth on purpose** and is labelled
`CONTROLLED_PERTURBATION` in the forecast object and in every exported row. It
is a mechanism probe. A reader who wants only leakage-safe results filters to
`forecast_mode ∈ {NONE, INDEPENDENT_MODEL_FORECAST}`.

**Weakest point:** two declared residuals (LEAKAGE_AUDIT §5). The ignition
distribution is conditioned on the village — shared by both policies, carrying
no per-world information, but it would become leakage if a future planner
learned a prior from the generator. And the static-context channel
(`docs/DECISIONS.md#d-006`) is *believed* small and **not measured**. The
experiment now makes that measurable: run the independent planner with and
without static context and compare skill. It has not been run.

## 2. Is the baseline strong enough?

**Probably, with one honest caveat.**

* It got the larger tuning budget by design: 144 configurations against the
  forecast-aware policy's 120.
* Its optimum is **interior** in both of the parameters that have room to be
  interior (`b₀` within 200–2000 m, `route_buffer_frac` within 0.05–0.60), so
  it is a real optimum rather than a grid edge.
* It acts on **73.6%** of resident-decisions and completes almost all of them;
  its protection-failure rate given a threatened resident is **22.0%**, against
  37.3% for the independent-model policy.
* Two secondary baselines (fixed buffer, fire-blind) and a non-operational
  oracle bound it from below and above.
* An earlier version of this experiment strangled the baseline by making one
  buffer serve both triggering and routing; it dispatched in 0 of 6 cases. That
  was found and fixed, and the same defect was then found and fixed in the
  forecast-aware policy (`PROTOCOL.md` §18).

**Caveat:** the baseline was tuned once, on 16 validation worlds, over a
four-parameter grid. It is a *strong* trigger/buffer policy, not a proof that
no trigger/buffer policy does better. Since the headline negative result is
"the independent planner did not beat it", the baseline's strength is exactly
the load-bearing assumption, and it deserves a wider search before that result
is published.

## 3. Is the planner independent enough?

**Yes, structurally — and the mismatch is documented rather than tuned.**

`docs/DECISIONS.md#d-019`. Different propagation (one analytic ellipse from an
estimated source, against travel-time accumulation over a heterogeneous raster),
different rate law in *form* (additive-linear in wind, against multiplicative
in a power of wind), different length-to-breadth law, and three declared
structural blind spots: no terrain, no fuel heterogeneity beyond the published
coarse class under its own mapping, no spotting. A test asserts those absences
against the module's executable source, so removing one requires a new decision
entry.

Its errors are **emergent**: CSI 0.066–0.133, with a systematic
under-prediction of spread that nobody set (`reports/FAILURE_ANALYSIS.md` §3).

**Weakest point:** it is *one* planner, and it is weak. Its low skill is why
its response surface is flat and why no final-split cell resolves. A better
independent planner might reach the frontier Mode A locates; this experiment
cannot say. "The independent planner did not beat the baseline" is a statement
about this planner, and the reports say so every time.

## 4. Are the world-generation assumptions documented?

**Yes, and all ten are labelled.**

`worlds.GENERATION_AUDIT`, reproduced in `reports/MVE_METHOD.md` §3 and in
every stage manifest: ignition location, wind speed, wind direction, wind
shift, fuel heterogeneity, terrain, spotting, route topology, village geometry,
resident capability.

**None is `DATA-INFORMED`.** Six are `ASSUMED`, four are `STRESS-TEST`. No
world here may be called Korean, and none is.

Generation rules were predeclared and worlds are never rejected for their
result; the only rejection rule is mechanical (a discretisation warning from
the laboratory).

**Weakest point:** the route topology is a perturbed lattice, which offers more
alternative paths than a real dendritic rural network and so plausibly
*understates* how often fire closes the only road.

## 5. Does the MVE produce interpretable paired outcomes?

**Yes.**

* Both policies run against the same `ExperimentWorld`, asserted at run time
  with identical hidden arrival times per resident.
* The baseline is verified θ-invariant rather than assumed to be, so computing
  it once per world is sound.
* 18 360 rows per 60-world stage, each carrying complete provenance — world,
  event, split, archetype, resident, policy, mode, regime, skill, outcome
  state, failure reason, loss and every loss component. Missing provenance
  fails the export.
* The outcome vocabulary is the declared one and never says "safe";
  self-evacuation is evaluated in parallel and gated on capability, never
  inferred from route existence.
* The surfaces are readable: Mode A gives a clean bounded frontier arc, Mode B
  a flat unresolved plane, and the failure taxonomy explains both
  (`reports/FAILURE_ANALYSIS.md`).

## 6. Can the experiment now scale?

**Yes, and it needs to — for Mode B specifically.**

Runtime, measured: about 1.9 s per world to generate, and about 40 minutes for
a full 60-world stage on one core. Generation and evaluation are both
embarrassingly parallel across worlds, so 500 worlds is roughly 5.5 hours
single-core and far less split across cores.

**Compute is not the constraint; Monte Carlo variance is.** Mode A resolves 21
of 25 cells at 60 worlds. Mode B resolves **0** of 25 on the final split and 11
of 25 on validation — it sits exactly at the edge of what 60 paired worlds can
see. Before any claim that Mode B is *worse* rather than *indistinguishable*,
the world count has to go up. The natural next run is Stage C at 300–500
worlds, with formal inference in `wildfireguardian-evaluation`.

Two things must scale with it: the diagnostics here are uncorrected across 50
cells, and several "resolved" cells are expected by chance alone.

## 7. What must change before Korean claims are possible?

Nothing in this experiment supports a Korean claim, and the reports contain
none. To get there:

**Necessary, in order:**

1. **Korean DEM** in place of synthetic terrain, with the archetypes redefined
   from real landform classes rather than from `flat / plane / ridge / noise`.
2. **A Korean fuel map**, which also closes `docs/ASSUMPTIONS.md#C-07` — the
   uncalibrated spread coefficients are `UNKNOWN` and currently make every
   spread rate in this laboratory arbitrary.
3. **Real road networks**, which replaces the lattice and will change the
   route-blocking results in a direction this experiment cannot predict.
4. **Korean weather-regime distributions**, so wind speed and direction stop
   being `Uniform` and the wind-shift rate stops being a declared 35%.
5. **Korean village archetypes**, so household placement and count are not
   `ASSUMED`.
6. **Real sensor specifications**, closing `docs/ASSUMPTIONS.md#D-08` — the
   cadence, latency and detection probability used here are invented, and the
   latency axis is the axis the headline result turns on.

**Also required before the results mean what they appear to mean:**

7. **Replace the dispatch placeholder** with
   `wildfireguardian-assisted-dispatch` through the existing adapter contract,
   and re-run the benchmarks before any stage.
8. **Model finite responder resources.** Until then no number is a population
   or system protection rate, and the phrase must not appear.
9. **Widen the propagation envelope.** The 16-direction stencil caps the usable
   wind at about 6 m·s⁻¹, so the experiment is silent about exactly the
   high-wind regimes where forecast value is most contested.

**And the reporting rule:** the generic synthetic result and any
Korean-anchored result must be reported **separately and never merged**. A
Korean-anchored run is a different experiment, and the frontier arc found here
is not a prior for it.

---

## Summary

| question | answer |
|---|---|
| 1. Leakage-safe? | Yes for Mode B, by four independent layers; Mode A is truth-derived and labelled. Two residuals declared, one unmeasured. |
| 2. Baseline strong enough? | Strong and interior-optimal, but tuned once over four parameters. It is the load-bearing assumption of the negative result. |
| 3. Planner independent enough? | Structurally yes, with three tested blind spots. But it is one planner, and a weak one. |
| 4. Assumptions documented? | All ten, labelled. None `DATA-INFORMED`. |
| 5. Interpretable paired outcomes? | Yes. Paired at run time, full provenance, readable surfaces, explained failures. |
| 6. Can it scale? | Yes. Compute is not the constraint; Mode B needs 300–500 worlds for variance. |
| 7. Korean claims? | Not yet, and none are made. Nine items listed, six of them data. |

**The single most valuable next step** is not more worlds: it is replacing the
dispatch placeholder, because every result here is conditional on a mission
model this repository wrote for itself.
