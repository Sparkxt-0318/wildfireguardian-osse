# MVE_READINESS

Answers to the seven questions that close this run. Evidence is linked; where
the answer is "no" or "partly", that is stated plainly.

---

## 1. Is the experiment leakage-safe?

**Yes for every path that was checked; no claim beyond that.**

Separation is enforced in code — `SealedTruth` raises on any truth access
inside a planner sandbox, `PlannerView.at(s)` filters on availability and
asserts its own filter, evaluator-only functions refuse to run from planner
code, and the runner verifies the hidden field is unchanged after each world.
Fifteen tests back the individual claims (`reports/LEAKAGE_AUDIT.md`).

Three open channels are documented rather than closed:

* **Mode A is truth-derived by construction** — a labelled mechanism probe, an
  oracle at zero error. Misreading a Mode A row as a realistic forecast is the
  easiest way to misuse this experiment.
* **Informative missingness** exists in the laboratory (`fire_correlated`),
  though Stage B did not use it.
* **Static context** (terrain, coarse fuel class) is planner-visible by
  decision; how much it narrows the fire's future is unmeasured.

---

## 2. Is the baseline strong enough?

**Yes — arguably stronger than the primary comparison gives it credit for.**

The tuned baseline uses the same state estimator as the forecast-aware policy,
chooses between routes on current evidence, and was grid-searched on the
validation split over 60 candidates (best 0.354, worst 0.421 — a flat surface,
so it is robust rather than knife-edge).

The honest finding: **on the held-out split it was beaten by a simpler fixed
buffer**, 0.237 against 0.267. Every `ΔJ` in this run is therefore measured
against a baseline that is ~0.03 worse than the best available one, which makes
the comparison mildly favourable to the forecast-aware policy. Re-running the
frontier against the best baseline is an open item.

---

## 3. Is the planner independent enough?

**Structurally yes; in capability, it is weak.**

Mode B shares no code, no parameters, no seeds and no state with nature. It
differs in structure, not just numbers: one analytic ellipse with a *linear*
rate law against nature's 16-direction raster front with a power-law rate,
heterogeneous fuel, terrain and spotting. It is built inside the planner
sandbox, which proves it needs no truth. Its errors come from the model gap and
from the observations, not from a knob.

But it is a simple model (CSI 0.12–0.29), and its advantage over the tuned
baseline (−0.039) shrinks to within noise against the best baseline. **The
flagship reading is that this independent model is about as good as a
well-tuned buffer, not better.** A stronger planner model would be the single
most informative addition.

---

## 4. Are the world-generation assumptions documented?

**Yes, and audited.** Every distribution appears in every run manifest under
`world_generation_audit`, classified ASSUMED or STRESS-TEST. **None is
DATA-INFORMED**, and the audit says so in its first line, so no synthetic
distribution can be mistaken for a Korean one.

The consequential one is flagged in two places: the ignition rule places fires
upwind of the village, which is why 58 of 60 worlds were threatened and why the
false-alarm side of the loss is barely exercised
(`reports/LIMITATIONS.md` §5).

---

## 5. Does the MVE produce interpretable paired outcomes?

**Yes.** Every policy and condition is evaluated against the identical hidden
world, verified by fingerprint and by test. One row per
`(world, mission kind, policy, condition, wait semantics)`, 10 200 rows for
Stage B, each carrying full provenance, exported for
`wildfireguardian-evaluation`.

The outcomes are interpretable enough to have produced non-obvious findings:
skill and value dissociate at matched CSI; the dominant failure is ordering
after the route closed rather than being cut en route; whether a break-even
frontier exists depends on the policy, not only the forecast.

---

## 6. Can the experiment now scale?

**Yes, with a clear cost model and one real constraint.**

Stage B: 60 worlds → 10 200 records in **130 s** single-threaded, ~2.2 s per
world, dominated by the nature simulation. Worlds are independent, so scaling
is linear and embarrassingly parallel. Stage C at 500 worlds is roughly 20
minutes single-threaded.

The constraint is not compute, it is **resolution**: 7 of 20 frontier slices
are `UNRESOLVED` at 60 worlds. Since the standard error falls as `1/√n`,
resolving contrasts about a third of the current size needs roughly an order of
magnitude more worlds — several hundred to low thousands. That is affordable.
Before spending it, the variance should be reduced structurally (common random
numbers across conditions are already in place; the remaining variance is
world-to-world heterogeneity, which a wider archetype set would spread rather
than shrink).

---

## 7. What must change before Korean claims are possible?

Nothing in this run supports a claim about Korea, and several things must
change before one could be attempted. In dependency order:

1. **Anchor the worlds.** Korean DEM, Korean fuel mapping, real road networks,
   Korean weather-regime distributions, Korean village archetypes. Until each
   is DATA-INFORMED in the audit, every result stays synthetic. Results from
   anchored worlds must be reported **separately** from these, never pooled.
2. **Calibrate the nature model.** `docs/ASSUMPTIONS.md#C-07` (rate of spread
   for Korean fuels) is `UNKNOWN`. An uncalibrated spread model cannot support
   a timing threshold, because the threshold is in minutes.
3. **Verify sensor specifications.** `docs/ASSUMPTIONS.md#D-08` is `UNKNOWN`.
   Latency conclusions are conditional on a latency axis nobody has validated.
   No sensor may be named after a real instrument until its specification comes
   from a primary source (`docs/DECISIONS.md#d-002`).
4. **Replace the placeholder dispatch adapter** with
   `wildfireguardian-assisted-dispatch`, through the existing contract. Present
   results are conditional on three hand-made semantics, and the non-monotone
   window they are supposed to govern is not even exercised here
   (`reports/LIMITATIONS.md` §2).
5. **Give the error regimes empirical provenance.** Every family is currently
   `TOY_MECHANISM` or `STRESS_TEST`. A threshold in degrees or minutes means
   nothing until the error distribution it sits in is `EMPIRICALLY_MOTIVATED`,
   and no probability may be placed over regimes until then.
6. **Model finite responder resources**, before any population-level statement.
7. **Run the loss sensitivity analysis**, and re-run the frontier against the
   best baseline rather than the primary one.
8. **Do the formal inference in `wildfireguardian-evaluation`** — bootstrap,
   equivalence, multiplicity — rather than reading the diagnostics here as
   results.

Only then, and only for anchored worlds, could a statement of the form "a
forecast must be accurate to within X and delivered within Y" be attempted —
and on this evidence it would also have to name **the policy that consumes the
forecast**, because the frontier's very existence depended on that.

---

## Stop condition

The six objectives for this run are met: the protocol is frozen
(`PROTOCOL.md`, `mve-1.1.0`), separation is validated
(`reports/LEAKAGE_AUDIT.md`), the staged experiment ran (A: 12 worlds,
B: 60 final-split worlds), evaluation records are exported
(`raw_outputs/evaluation_records_mve_stage_b.csv`), a preliminary frontier
exists (`reports/FRONTIER_RESULTS.md`), and the Korean-anchoring requirements
are enumerated above.

**Stage C is scoped but deliberately not run**, and the main WildfireGuardian
repository was not integrated, per the brief.
