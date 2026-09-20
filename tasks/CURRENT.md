# CURRENT

## Active

Nothing in progress. Phase 1 (the laboratory) and Phase 1b (the forecast-value
experiment) are both complete — see `tasks/COMPLETED.md`. Phase 2 has not been
started and should not be until the Phase 1 limitations below have been
reviewed.

## Next up (from `tasks/ROADMAP.md`, highest value first)

1. **Spatially varying wind field.** The largest single unrealism. Today wind is
   uniform, so weather stations differ only by noise and *spatial* data
   assimilation cannot be studied at all (`docs/ASSUMPTIONS.md#B-01`).
   Agent A must specify the field model and its observation semantics before any
   code: a spatial field changes what a station observation *means*.
2. **A better propagation stencil or a fast-marching solver.** The current
   16-direction stencil under-predicts burned area once the spread ellipse
   becomes eccentric, which caps the usable wind range at about 6 m/s
   (`docs/VALIDATION.md#4`). This is the binding constraint on the parameter
   space the laboratory can sweep.
3. **Fireline intensity as a derived field**, so detection probability can
   depend on intensity rather than on burning area alone
   (`docs/ASSUMPTIONS.md#D-03`).

## Deferred — out of scope for the laboratory package (`docs/SCOPE.md`)

Recorded rather than implemented **inside `wildfireguardian_osse`**. The
laboratory must never import any of these, and a test enforces it
(`tests/fv/test_package_separation.py`).

* Ingestion of real observational data.
* Any integration with another WildfireGuardian repository
  (`docs/DECISIONS.md#d-001`). Mission feasibility enters the experiment
  package through an adapter contract instead (`docs/DECISIONS.md#d-018`).

Now built in the **separate** `wildfireguardian_fv` package, one-way dependent
on the laboratory (`docs/DECISIONS.md#d-017`):

* Road-network exposure, as planner-visible static context.
* Assisted-evacuation outcome modelling, through the adapter contract.
* Forecast-value / decision-value analysis
  (`experiments/forecast_value_mve/`).

## Next up for the forecast-value experiment

The full list, with what each one blocks, is in
`experiments/forecast_value_mve/reports/MVE_READINESS.md`. The three that most
limit what can currently be claimed:

1. **The dispatch placeholder.** Until it is replaced, no result may be
   described as using assisted-dispatch semantics.
2. **No responder resource constraint.** No number is a population or system
   protection rate, and the phrase must not appear.
3. **Only two error families are swept.** Spread-rate bias, displacement and
   missed spotting are specified and unswept.

## Open questions for Agent A (Model Auditor)

* **Informative missingness.** `fire_correlated` mode makes absence correlate
  with the hidden fire (`docs/FAILURE_MODES.md#F-05`). It is not leakage and it
  is deliberate, but no test currently bounds *how much* a consumer could learn
  from the absence pattern. Quantifying that channel would sharpen the claim.
* **Static context.** Terrain and coarse fuel class are planner-visible
  (`docs/DECISIONS.md#d-006`). Combined with a detection, how much does the
  static context narrow the fire's future? Believed small because ignition,
  wind and the spread parameters are all hidden — but believed, not measured.
* **The static-context channel, now measurable.** The forecast-value
  experiment gives a way to ask the question below quantitatively: run the
  independent planner with and without static context and compare skill. It has
  not been run (`reports/LEAKAGE_AUDIT.md#5`).
* **`UNKNOWN` quantities.** `docs/ASSUMPTIONS.md` lists six. The two that most
  limit interpretation are `C-07` (calibrated rate of spread for Korean fuels)
  and `D-08` (real sensor detection probability, cadence and latency). Either
  can only be closed from a primary source, never by a plausible guess
  (`docs/DECISIONS.md#d-002`).

## Standing reminders

* Docs before code (`AGENTS.md#3`).
* New randomness goes through a named stream; `grep -rn "np\.random\." src/`
  must match nothing outside `rng.py`.
* Append to `docs/DECISIONS.md`; never edit an existing entry.
* `pytest -q` and `wg-osse selftest` green before any commit.
