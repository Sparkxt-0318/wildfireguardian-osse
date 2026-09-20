# MVE_RESULTS — what happened

> **Synthetic OSSE experiment.** Generic synthetic worlds; no Korean DEM, fuel
> map, road network, village archetype or weather regime constrains anything
> here. Nothing below is a requirement for Korean wildfire operations.

Design: `../PROTOCOL.md`. Implementation: `MVE_METHOD.md`. Every number quoted
here is in `../raw_outputs/summary_stage{A,B,C}.json`, computed from the
committed outcome rows by `wg-fv summary`.

---

## 1. What was run

| stage | split | worlds | rows | status |
|---|---|---|---|---|
| A | development (`open_plain`, `rolling_noise`) | 12 | 3 672 | debug semantics |
| B | validation (`sloped_valley`, `mosaic_barrier`) | 60 | 18 360 | variance and runtime |
| C | **final** (`ridge_channel`, `plateau_step`) | 60 | 18 360 | one frozen pass |

50 forecast conditions per world (5 direction errors × 5 latencies × 2 modes),
plus the θ-invariant baseline. Splits share no landscape archetype, so the
final worlds are a different family of landscapes, not different draws from the
tuning family.

Runtime, single core and measured rather than estimated: about **1.9 s** per
world to generate, and about **40 minutes** for a full 60-world stage
(60 worlds × 51 policy runs each). Monte Carlo noise, not compute, is the
binding constraint (§6).

## 2. Headline

**The two questions, answered for this OSSE:**

1. **How accurate and how timely must a forecast be?** With a forecast built by
   degrading hidden truth (Mode A), forecast-aware action beat the tuned
   baseline up to a direction error of about **22°** when delivered instantly,
   about **18°** at 15 minutes' latency, and about **9°** at 30 minutes. At
   **60 minutes' latency there is no crossing at all**: no accuracy in the
   swept range was worth acting on. Along the other axis, a perfect-direction
   forecast broke even at about **39 minutes** of latency, and a 10°-biased one
   at about **25 minutes**.
2. **Is conventional forecast skill sufficient to predict decision value?**
   **No.** At CSI = 1.000 — a forecast that reproduces the hidden field exactly
   — `ΔJ` ranged from **−0.136 to +0.142** on the final split, a sign change,
   driven entirely by latency. Skill predicted value almost perfectly *at fixed
   latency* (ρ = −1.0 in every latency row) and only moderately overall
   (ρ = −0.84). Timeliness is not recoverable from a skill score.

**And a negative result, reported as one:** the structurally independent
planner (Mode B) **did not outperform the tuned baseline anywhere**, in any
condition, on any split. On the final split not one of its 25 cells resolved
away from zero; every point estimate was positive (baseline better) but small,
+0.006 to +0.040.

## 3. The response surfaces (final split)

`ΔJ = J_forecast − J_baseline`. Negative favours the forecast-aware policy.
ᵘ marks a cell whose paired bootstrap interval covers zero.

### Mode A — `CONTROLLED_PERTURBATION` (built from truth; a mechanism probe)

| latency \ direction error | 0° | 10° | 20° | 35° | 55° |
|---|---|---|---|---|---|
| **0 min** | −0.136 | −0.084 | −0.006 ᵘ | +0.091 | +0.165 |
| **5 min** | −0.126 | −0.071 | −0.010 ᵘ | +0.094 | +0.168 |
| **15 min** | −0.120 | −0.050 | +0.019 ᵘ | +0.109 | +0.177 |
| **30 min** | −0.061 | −0.015 ᵘ | +0.073 | +0.128 | +0.184 |
| **60 min** | +0.142 | +0.176 | +0.206 | +0.217 | +0.235 |

21 of 25 cells resolved; 7 favour the forecast, 14 the baseline.

### Mode B — `INDEPENDENT_MODEL_FORECAST` (the flagship; leakage-safe)

| latency \ direction error | 0° | 10° | 20° | 35° | 55° |
|---|---|---|---|---|---|
| **0 min** | +0.017 ᵘ | +0.023 ᵘ | +0.024 ᵘ | +0.034 ᵘ | +0.031 ᵘ |
| **5 min** | +0.022 ᵘ | +0.006 ᵘ | +0.017 ᵘ | +0.028 ᵘ | +0.028 ᵘ |
| **15 min** | +0.024 ᵘ | +0.018 ᵘ | +0.019 ᵘ | +0.030 ᵘ | +0.026 ᵘ |
| **30 min** | +0.024 ᵘ | +0.021 ᵘ | +0.025 ᵘ | +0.033 ᵘ | +0.027 ᵘ |
| **60 min** | +0.040 ᵘ | +0.036 ᵘ | +0.039 ᵘ | +0.034 ᵘ | +0.027 ᵘ |

**0 of 25 cells resolved.** The surface is also nearly flat: degrading a
forecast that is already this weak barely changes the decision. Its CSI ranged
only 0.066–0.133, so the injected direction bias is small next to the error the
planner already had.

Validation (Stage B) agreed in structure and resolved 11 of Mode B's 25 cells,
all favouring the baseline. The final split is the weaker statement of the two,
and it is the one that counts.

## 4. Break-even structure

Crossings are reported as **brackets between resolved grid points**, with a
linear interpolate inside. Nothing is drawn through a region the data do not
resolve.

| latency | classification | bracket | interpolated break-even |
|---|---|---|---|
| 0 min | `SINGLE_CROSSING` | 10°–35° | ≈ 22.0° |
| 5 min | `SINGLE_CROSSING` | 10°–35° | ≈ 20.8° |
| 15 min | `SINGLE_CROSSING` | 10°–35° | ≈ 17.9° |
| 30 min | `SINGLE_CROSSING` | 0°–20° | ≈ 9.1° |
| 60 min | `NO_CROSSING_BASELINE_BETTER` | — | none exists in the grid |

Along the latency axis: break-even at ≈ 39 min for a perfect-direction
forecast, ≈ 25 min at 10° error, and no crossing at 20° or worse.

Every bracket spans one unresolved cell, so the interpolated values are
**locations within a bracket, not estimates with an interval**. The full
structure, including the unresolved cells, is in `FRONTIER_RESULTS.md`.

`all_slices_monotone` is **false** on the final split: the surface is not
monotone everywhere, and the frontier is not claimed to be.

## 5. Behaviour, not just loss

Final split, per policy family:

| | act-now rate | mean `J` | protection failures, given threatened |
|---|---|---|---|
| baseline | 73.6% | 0.2302 | 37 / 168 (22.0%) |
| Mode A (all conditions) | 27.0% | 0.2905 | 2 325 / 4 200 (55.4%) |
| Mode B (all conditions) | 56.3% | 0.2563 | 1 565 / 4 200 (37.3%) |

The forecast means average over the whole error grid, including severely
degraded conditions the baseline never faces, so they are not a like-for-like
comparison — the paired cells in §3 are. What they do show is a real
behavioural difference: **the tuned baseline acts far more often**, and in
these worlds acting often is cheap and failing to act is expensive.

Outcome states are reported in the declared vocabulary and never as "safe".
Self-evacuation is scored separately: on the final split 204 of 360
baseline resident-outcomes were `RESIDENT_NOT_SELF_EVACUATION_CAPABLE`, 154
`SELF_EVACUATION_FEASIBLE` and 2 `NO_SELF_EVACUATION_ROUTE` — capability, not
route existence, is what mostly decides it, which is the intended semantics.

## 6. Is this Monte Carlo noise?

Partly, for Mode B, and the report says so rather than reading through it.

* Mode A at 60 worlds resolves 21 of 25 cells; its effects (|ΔJ| up to 0.235)
  are large relative to the paired spread.
* Mode B at 60 worlds resolves **0** of 25; its effects (|ΔJ| ≤ 0.040) are not.
  Stage B resolved 11 of 25 at the same world count, so Mode B sits near the
  edge of what 60 worlds can see. **More worlds would be required before any
  claim that Mode B is worse rather than indistinguishable.**
* These are uncorrected per-cell diagnostics across 50 cells. Several
  "resolved" cells are expected by chance alone. Formal inference is
  `wildfireguardian-evaluation`'s job; the rows are exported for it.

## 7. Constructed benchmark validation

Run on development worlds before the stages (`../raw_outputs/benchmarks.json`).
A `DEMONSTRATED` benchmark shows the experiment can *express* the regime; it
says nothing about how often the regime occurs.

| case | status | evidence |
|---|---|---|
| `ACCURATE_BUT_LATE` | **DEMONSTRATED** | CSI 1.000 → 1.000, `ΔJ` −0.121 → +0.079 |
| `FORECAST_HARM` | **DEMONSTRATED** | four of the five regimes had `ΔJ` > 0 |
| `SIMILAR_SKILL_DIFFERENT_VALUE` | **DEMONSTRATED** | CSI 1.000/1.000, `ΔJ` −0.121 vs +0.079; and CSI 0.239/0.239, `ΔJ` +0.085 vs +0.162 |
| `CRUDE_BUT_TIMELY` | **NOT DEMONSTRATED** | crude/timely `ΔJ` +0.085 was *worse* than accurate/late +0.079 |
| `BASELINE_MATCH` | **NOT DEMONSTRATED** | no benchmark regime had \|`ΔJ`\| ≤ 0.02 |

The five benchmark conditions, on development worlds
(`J_baseline` = 0.2336 throughout, since the baseline is θ-invariant):

| condition | CSI | `J_forecast` | `ΔJ` |
|---|---|---|---|
| accurate, timely (0°, 0 min) | 1.000 | 0.1123 | **−0.121** |
| accurate, late (0°, 60 min) | 1.000 | 0.3129 | +0.079 |
| crude, timely (35°, 0 min) | 0.239 | 0.3185 | +0.085 |
| crude, late (35°, 60 min) | 0.239 | 0.3955 | +0.162 |
| severe, timely (55°, 0 min) | 0.140 | 0.3678 | +0.134 |

Two cases did not fire, and both are informative rather than gaps in the
machinery:

* **`CRUDE_BUT_TIMELY`.** In these worlds a 35° direction error is more
  damaging than a 60 minute delay (+0.085 against +0.079), so "crude but
  timely" does not beat "accurate but late" here. The same ordering appears on
  the final split — compare the 55°/0 min cell (+0.165) with the 0°/60 min cell
  (+0.142). It is a statement about **this** loss, **these** worlds and **this**
  mission model, not a general one, and the opposite ordering is perfectly
  constructible in a world set where travel times are longer.
* **`BASELINE_MATCH`.** None of the five declared benchmark conditions landed
  within ±0.02 of the baseline. The **full grid does** contain such cells — the
  final-split 20°/0 min and 20°/5 min cells are `ΔJ` −0.006 and −0.010 — so the
  regime is expressible; the benchmark set, which is five fixed points, simply
  did not sample one. Widening it after seeing this would be tuning the
  validation to pass, so it was left alone and reported.

## 8. Protocol deviations

The protocol was frozen three times. Both re-freezes were triggered by defects
found on **validation-split** data, and in both cases the stage-C run in flight
was stopped and its files deleted before any of its output was read, so the
final split was still read exactly once, after the final freeze. Full text in
`../PROTOCOL.md` §18.

* **Freeze 1 → 2.** The forecast-aware policy had one buffer doing two jobs
  (route blocking and threat triggering) while the baseline had two. Tuning
  shrank the shared buffer to 150 m, and the policy acted on 16% of decisions
  against the baseline's 71% — the asymmetry, not the forecast, was doing the
  work. Split into two parameters; all stages re-run.
* **Freeze 2 → 3.** The forecast-aware policy was tuned against Mode B only and
  those parameters were carried into Mode A. Mode B's forecast under-predicts
  spread, so tuning against it selected a policy that leans on its observed-fire
  trigger; running Mode A under it would have confounded "an accurate forecast
  is not worth acting on" with "this policy was set up not to act on one".
  Tuning is now per mode; all stages re-run.
* **Analysis, not experiment.** The frontier classifier originally required the
  two sides of a sign change to be *adjacent* grid points. The cell nearest zero
  is exactly the cell whose interval covers zero, so that rule hid a crossing
  precisely when the grid bracketed it well. Brackets are now sought between
  consecutive *resolved* points and flagged when they span an unresolved cell.
  This changed no loss and no decision.

## 9. What may and may not be said

**Supported by this experiment:**

* Under this declared OSSE, forecast-aware action outperformed the tuned
  trigger/buffer baseline in the low-error, low-latency region of the swept
  grid when the forecast was constructed by degrading hidden truth, and did not
  outperform it anywhere when the forecast came from an independent model.
* Conventional forecast skill was **not** sufficient to explain decision value
  across these worlds: identical CSI produced opposite signs of `ΔJ`.
* Break-even regions were not monotone everywhere under this experiment, and
  vanish entirely beyond about 40 minutes of product latency.

**Not supported, and not stated anywhere:**

* any number of degrees or minutes as a requirement for Korean wildfire
  forecasts, or as an operational threshold;
* any claim about lives;
* any system or population protection rate — feasibility here is per mission,
  with no responder fleet modelled.

## 10. Figures

`../figures/fig{1..5}_*_stageC.png`, with Stage A and B counterparts.

1. forecast skill against decision value — the vertical spread at CSI = 1.000
   is the headline;
2. the error × latency response surface, per mode, with unresolved cells named;
3. break-even structure with every crossing shown as a bracket;
4. failure-reason composition, normalised to each family's own decisions;
5. one final-split world where the two policies chose differently.
