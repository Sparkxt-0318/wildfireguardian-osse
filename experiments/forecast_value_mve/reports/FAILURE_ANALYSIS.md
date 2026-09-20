# FAILURE_ANALYSIS — why the policies fail

> Synthetic OSSE experiment. Not Korean-anchored.

Counts are final-split (Stage C) unless stated. Every figure is in
`../raw_outputs/summary_stageC.json`; the composition is drawn in
`../figures/fig4_failure_composition_stageC.png`, normalised to each family's
own decision count because the baseline contributes 360 rows and each forecast
mode 9 000.

Two kinds of reason are distinguished throughout:

* **`BELIEF_*`** — the policy declined to act because *its own belief* said no
  feasible mission existed. The world may disagree.
* everything else — the mission was attempted or omitted, and **hidden truth**
  decided the outcome.

---

## 1. The baseline (tuned trigger/buffer)

Acts on 73.6% of resident-decisions. Of 168 resident-outcomes where the fire
actually reached the house within the horizon, 37 (22.0%) were protection
failures.

All 129 of its non-completions:

| reason | count | what it means |
|---|---|---|
| `OUTSIDE_TRIGGER_BUFFER` | 48 | never triggered: the fire never came within 1000 m of the house before the horizon, or came too late |
| `ROUTE_BLOCKED_BY_FIRE` | 30 | dispatched, and hidden truth closed a road during the traversal |
| `BELIEF_MISSION_EXCEEDS_HORIZON` | 24 | triggered late; no mission could finish in time |
| `BELIEF_NO_ROUTE_TO_RESIDENT` | 16 | the 150 m routing clearance left no way in |
| `BELIEF_FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` | 7 | the house was inside the observed fire by the time it triggered |
| `FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` | 4 | dispatched, and the fire won the race to the house |

**The baseline's dominant failure is being late, not being wrong.**
`OUTSIDE_TRIGGER_BUFFER` plus `BELIEF_MISSION_EXCEEDS_HORIZON` is 72 of its 129
non-completions: it waits for the fire to come close enough to see, and by then
the clock has run out. That is exactly the weakness a forecast is supposed to
fix — and it is why the Mode A frontier exists at all.

Its second failure, `ROUTE_BLOCKED_BY_FIRE` (30), is the one a forecast is
*also* supposed to fix: the baseline plans around where the fire **is**, so a
road that is clear at dispatch and burning at traversal is invisible to it. Its
tuned routing clearance is only 150 m, which buys speed at the cost of these.

## 2. Mode A — an accurate forecast, degraded in a named way

Acts on 27.0% of decisions across the whole grid. Of its 6 704 non-completions,
two reasons account for **98%**:

| reason | count | share of non-completions |
|---|---|---|
| `NO_PREDICTED_THREAT` | 4 235 | 63.2% |
| `BELIEF_FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` | 2 339 | 34.9% |
| `ROUTE_BLOCKED_BY_FIRE` | 76 | 1.1% |
| `FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` | 54 | 0.8% |

These two tell the whole story of the frontier:

* **`NO_PREDICTED_THREAT` is mostly correct.** Tuned for an accurate forecast,
  this policy uses a 150 m observed-fire buffer — it trusts the forecast and
  almost ignores the crude trigger. When the forecast says a house is not going
  to burn, it does not dispatch. In the undegraded corner that is right, and it
  is where its loss is lowest (`ΔJ` = −0.136). Under a 55° rotation the same
  confidence points at the wrong houses, and the same reason code is now a
  mistake. **The identical mechanism produces the best and the worst cells of
  the surface.**
* **`BELIEF_FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` is the latency
  failure.** The belief is right about *where*, and late about *when it was
  learned*. At 60 minutes' latency the policy is reasoning about a house the
  forecast already shows as overrun; it declines, correctly under its belief
  and too late to matter. This is the mechanism behind the entire 60-minute row
  being worse than the baseline at every accuracy.

Notice how few Mode A failures are `ROUTE_BLOCKED_BY_FIRE` (76, against the
baseline's 30 in a 25× smaller sample — **0.8% of Mode A's decisions against
8.3% of the baseline's**).
**When the forecast is accurate, the roads it picks stay open.** The value it
adds is in route choice and timing, and it is lost to latency rather than spent
on bad routes.

## 3. Mode B — the independent planner

Acts on 56.3% of decisions — more often than Mode A, because tuning gave it a
700 m observed-fire trigger to lean on. Of 4 200 threatened resident-outcomes,
1 565 (37.3%) were protection failures.

All 4 988 of its non-completions:

| reason | count | share of non-completions |
|---|---|---|
| `NO_PREDICTED_THREAT` | 2 123 | 42.6% |
| `ROUTE_BLOCKED_BY_FIRE` | 903 | 18.1% |
| `BELIEF_FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` | 635 | 12.7% |
| `BELIEF_NO_ROUTE_TO_RESIDENT` | 561 | 11.2% |
| `BELIEF_MISSION_EXCEEDS_HORIZON` | 540 | 10.8% |
| `FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` | 153 | 3.1% |
| `BELIEF_NO_ROUTE_TO_DESTINATION` | 73 | 1.5% |

**The diagnosis is under-prediction.** The planner's rate law is
`R = 2.6 + 1.6·U` m·min⁻¹ against nature's `R₀(1 + 0.40·U^1.5)`; at 4 m·s⁻¹
that is roughly 9–10 against 12–13 m·min⁻¹. It also has no slope term, no fuel
heterogeneity and no spotting (`docs/DECISIONS.md#d-019`). The consequences
compound:

1. **It predicts arrival too late**, so `NO_PREDICTED_THREAT` fires when the
   house will in fact burn — 42.6% of its failures.
2. **It predicts a smaller fire**, so its belief has clear roads that hidden
   truth does not: `ROUTE_BLOCKED_BY_FIRE` is 903 cases, 18.1% of its failures
   and **10.0% of all its decisions against Mode A's 0.8%** — twelve times the
   rate. This is the
   characteristic error of an under-predicting forecast — it does not decline
   to move, it moves into fire.
3. **Its CSI is 0.066–0.133.** At that skill level the injected direction bias
   is a small perturbation of an already-wrong field, which is why its response
   surface is flat and why no cell resolves.

A second, subtler effect: `BELIEF_NO_ROUTE_TO_RESIDENT` (561) and
`BELIEF_MISSION_EXCEEDS_HORIZON` (540) together are 22.1% of its failures, and
both are absent from Mode A's taxonomy entirely. Merging a wrong forecast with
the observed fire by element-wise minimum can make the belief *pessimistic in
the wrong place*: the predicted ellipse lies across a road the real fire never
reaches, and the policy refuses a mission that would have worked.

**So the independent planner fails in both directions at once** — too
optimistic about the fire's speed, too pessimistic about the specific roads it
predicts wrongly. That is what model error looks like when it is emergent
rather than injected, and it is the main reason Mode B never reaches the
frontier Mode A locates.

## 4. Figure 5: one world, drawn out

`../figures/fig5_example_world_stageC.png` shows final-split world 67 000
(`plateau_step`). The baseline dispatched to five residents at 60–120 minutes
and all five missions completed under hidden truth. The Mode B forecast-aware
policy held for all five, each with
`BELIEF_FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE` — its under-predicting
ellipse, merged with the observed fire, put the houses inside a believed burn
front that the real fire reached much later.

This is the Mode B mechanism in one world: not a forecast that says "no
threat", but one that says "too late" while the baseline, looking only at where
the fire actually was, went and got everyone.

## 5. What the failure taxonomy required

Two ordering decisions were forced by this analysis and are now part of the
adapter contract:

* **The resident is checked before the roads.** A house already inside the fire
  used to be reported as `NO_ROUTE_TO_RESIDENT`, which is true and useless: the
  reason the mission cannot happen is the fire at the house. Without the fix,
  Mode A's dominant failure mode would have been mislabelled as a routing
  problem.
* **`BELIEF_*` reasons are kept distinct from truth-side reasons.** Collapsing
  them would have made "the policy declined" and "the policy tried and failed"
  indistinguishable — and those are the two halves of §2 and §3 respectively.

## 6. What is not diagnosed here

* Whether a *better* independent planner would reach the frontier. Only one was
  built (`docs/DECISIONS.md#d-019`), and its blind spots drive its errors.
* Whether the baseline's `OUTSIDE_TRIGGER_BUFFER` failures are irreducible. A
  larger buffer was in the search grid (up to 2000 m) and lost; that is a
  statement about this loss's dispatch costs, not a proof.
* Anything about responder fleets. Every mission is evaluated independently, so
  no failure here is a contention failure.
