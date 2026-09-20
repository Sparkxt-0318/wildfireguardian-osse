# FRONTIER_RESULTS — current break-even analysis

`ΔJ(e, δ) = J_forecast-aware − J_baseline_tuned_buffer`, paired within worlds.
Source: `../raw_outputs/frontier.json`, Figure 3.

Nothing here assumes the break-even set is monotone, connected, single-valued,
convex, or that it exists. A latency slice is `CROSSING`,
`MULTIPLE_CROSSINGS`, `NO_CROSSING` or `UNRESOLVED`, and **nothing is
interpolated inside an unresolved band**.

"Resolved" means the paired mean exceeds twice its standard error over 60
worlds — a **lightweight diagnostic, not formal inference**. Formal inference
(bootstrap, TOST, equivalence, multiplicity) belongs to
`wildfireguardian-evaluation`, which is why the per-world records are exported.

## Self-evacuation, controlled perturbation

| latency (min) | frozen policy (margin 90) | aggressive probe (margin 0) |
|---|---|---|
| 0 | `NO_CROSSING` — forecast-aware better throughout | `CROSSING` between `none` and `medium` |
| 5 | `NO_CROSSING` — forecast-aware better throughout | `CROSSING` between `none` and `medium` |
| 15 | `NO_CROSSING` — forecast-aware better throughout | `CROSSING` between `none` and `medium` |
| 30 | `UNRESOLVED` | `NO_CROSSING` — baseline better throughout |
| 60 | `UNRESOLVED` | `UNRESOLVED` |

Assisted evacuation gives the same pattern with larger absolute losses.

## What this says

**1. For the frozen policy there is no break-even frontier in the tested
range.** At latencies up to 15 minutes the conservative forecast-aware policy
is better than the tuned baseline at *every* error level, including `severe`
where its mean `ΔJ` is positive but not separable from noise. There is no
accuracy threshold to report, because accuracy never becomes the binding
constraint. Reporting a threshold anyway would be inventing one.

**2. For the aggressive probe a frontier does exist**, bracketed between the
`none` and `medium` error levels at latencies 0–15 min. It is *bracketed*, not
located: the `low` level sits between them and is `UNRESOLVED` at 60 worlds, so
the crossing could lie anywhere in `(none, medium)`. It is not interpolated.

**3. The frontier's existence depends on how the forecast is used, not only on
how good it is.** The same forecasts, the same worlds, the same loss: a
conservative policy has no frontier, an aggressive one has a sharp one. Any
statement of the form "a forecast must be accurate to within X before it pays"
is therefore incomplete without naming the policy that consumes it.

**4. Beyond 30 minutes of latency the question dissolves.** At 60 minutes every
cell equals the baseline exactly — the forecast arrives after the decision has
been taken — so there is nothing to cross.

## `UNRESOLVED` is a result, not a gap

Seven of twenty slices are `UNRESOLVED` at 60 worlds. That is the honest state
of the evidence: the paired contrasts there are smaller than Monte-Carlo noise.
Resolving them needs more worlds (Stage C) or a lower-variance design, not a
smoother curve. See `MVE_READINESS.md` for the sample-size implication.

## Caveats that bound every line above

* Measured against the **primary** baseline. The *best* baseline on this split
  (fixed buffer) is 0.030 better, which would shift every `ΔJ` upward by about
  that amount and could move the `NO_CROSSING` verdicts at latency 15 toward
  `UNRESOLVED`. The frontier analysis has **not** been re-run against the best
  baseline; that is an open item.
* Conditional on the declared loss weights. No sensitivity analysis yet.
* Mode A is truth-derived. The frontier shape is a statement about *controlled
  displacement*, not about the errors any real forecast makes.
