# CURRENT

## Active

Nothing in progress. Phase 1 (laboratory) and the forecast-value MVE are both
complete (`tasks/COMPLETED.md`).

## Next up for the forecast-value experiment

Ordered by how much each one changes what may be concluded. Full reasoning in
`experiments/forecast_value_mve/MVE_READINESS.md`.

1. **Loss sensitivity analysis.** Every MVE number is conditional on
   `mve-loss-1.1.0`, whose failure and premature-action terms are within a
   factor of two of each other. Nothing else should be scaled up before this.
2. **Re-run the frontier against the best baseline, not the primary one.** The
   tuned baseline lost to a simpler fixed buffer on the held-out split, so
   every `ΔJ` is ~0.03 favourable to the forecast-aware policy.
3. **A stronger independent forecast model.** Mode B reaches CSI 0.12–0.29 and
   its advantage over a well-tuned buffer is within noise. Conclusions about
   forecast value rest on Mode B, so its weakness bounds them.
4. **Replace the placeholder dispatch adapter** with
   `wildfireguardian-assisted-dispatch` through the existing contract.
5. **Fix the false-alarm blind spot.** 58 of 60 Stage B worlds were threatened,
   so `unnecessary_action` fired twice and over-evacuating is barely punished —
   a bias pointing the same way as the headline result.
6. **Stage C** (several hundred worlds) to resolve the 7 of 20 `UNRESOLVED`
   frontier slices. Compute is not the constraint; ~2.2 s per world.

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

## Deferred — out of scope here (`docs/SCOPE.md`)

Recorded rather than implemented. If a task seems to need one of these, it
belongs in another repository.

* Routing / road-network exposure.
* Evacuation and assisted-rescue outcome models.
* Forecast-value or decision-value analysis.
* Ingestion of real observational data.
* Any integration with another WildfireGuardian repository
  (`docs/DECISIONS.md#d-001`).

## Open questions for Agent A (Model Auditor)

* **Informative missingness.** `fire_correlated` mode makes absence correlate
  with the hidden fire (`docs/FAILURE_MODES.md#F-05`). It is not leakage and it
  is deliberate, but no test currently bounds *how much* a consumer could learn
  from the absence pattern. Quantifying that channel would sharpen the claim.
* **Static context.** Terrain and coarse fuel class are planner-visible
  (`docs/DECISIONS.md#d-006`). Combined with a detection, how much does the
  static context narrow the fire's future? Believed small because ignition,
  wind and the spread parameters are all hidden — but believed, not measured.
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
