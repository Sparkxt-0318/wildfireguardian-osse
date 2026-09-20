# LIMITATIONS — what remains artificial

Ordered by how much each one constrains what may be concluded.

## 1. Nothing here is Korean-anchored

No distribution in the world generator is constrained by Korean data — the
audit in every manifest classifies each as ASSUMED or STRESS-TEST, and **none**
as DATA-INFORMED. Terrain is synthetic, fuels are synthetic, the road network
is five nodes, the village geometry is identical in every world. No statement
about Korean wildfires, Korean forecasts or operational requirements follows
from any of it.

## 2. The mission semantics are a placeholder, not the real package

`wildfireguardian-assisted-dispatch` was not available. `placeholder-dispatch-0.1.0`
implements three semantics only: full edge traversal intervals, pickup
duration, coherent scenarios. **Absent:** fleet constraints, multiple
responders, resident heterogeneity, multi-stop routing, re-tasking, and
anything about capacity. Results are conditional on these semantics and a
different adapter could move them.

### The non-monotone dispatch window is expressible but **not exercised**

The adapter can produce a feasible window that closes and reopens
(`tests/test_missions.py`), which is the property the brief asks these semantics
to govern. Measured on the actual MVE worlds, it never happens: over 8 worlds ×
2 routes × 17 order times, feasibility with the declared 60-minute road
blockage is **identical** to feasibility with permanent blockage. Reopening
appears only at a blockage duration of ~5 minutes (16 differences, 10
reopenings). Within this geometry and 180-minute horizon the fire never crosses
a route early enough to reopen before the decision window ends. **Effective
feasibility in the MVE is monotone in order time**, and any conclusion that
depends on non-monotonicity is unsupported here.

## 3. Single-mission feasibility, not population outcomes

Every mission is evaluated independently. There is no fleet, no queue, no
contention. This is **not** a system protection rate and is never reported as
one. Finite responder resources must be modelled before any population-level
policy claim.

## 4. The loss is declared, not validated

`mve-loss-1.1.0` weights are a modelling choice, revised once against measured
degeneracy (`docs/DECISIONS.md#d-017`). **No sensitivity analysis has been
run.** Because failure (1.0) and premature action (0.5 + 0.3/h) are within a
factor of two of each other, conclusions could move under different weights.
This is the first thing a sceptical reader should ask for, and the first item
of future work.

## 5. The false-alarm side is barely tested

The ignition rule places fires upwind of the village, so 58 of 60 Stage B
worlds were threatened. `unnecessary_action` fires twice. A policy that
over-evacuates is therefore under-punished, which systematically favours
conservative policies — including the frozen forecast-aware policy, whose
90-minute margin makes it conservative. **This is a known bias in the current
world generator, and it points the same way as the headline result.**

## 6. Mode A is truth-derived

`CONTROLLED_PERTURBATION` is a mechanism probe. At zero error and zero latency
it is an oracle. Its `ΔJ` surface describes how *controlled displacement*
propagates into decisions, not what any real forecast does. Conclusions meant
to be about real forecasting must rest on Mode B — where the honest reading is
that the independent model is about as good as a well-tuned buffer, and no
better.

## 7. The independent model is deliberately simple

One ellipse, persisted wind, a linear rate law, no terrain, no fuel map, no
spotting. It is structurally different from nature (which is the point) but it
is not a serious forecasting system, and its skill (CSI 0.12–0.29) is low. A
better independent model could land anywhere on Figure 1.

## 8. Statistical resolution

60 worlds leave 7 of 20 frontier slices `UNRESOLVED`. The separability test is
a paired mean against twice its standard error — a diagnostic, not inference.
No bootstrap, no equivalence testing, no multiplicity correction: those belong
to `wildfireguardian-evaluation`, and the per-world records are exported for
exactly that reason.

## 9. Inherited limitations of the OSSE itself

* Wind is **spatially uniform**, so weather stations differ only by noise and
  spatial assimilation cannot be studied (`docs/ASSUMPTIONS.md#B-01`).
* Spread coefficients are uncalibrated (`docs/ASSUMPTIONS.md#C-07`, UNKNOWN).
* No real sensor is modelled (`docs/ASSUMPTIONS.md#D-08`, UNKNOWN).
* The 16-direction stencil under-predicts burned area above ~6 m/s wind, which
  caps the wind range the sweep may use (`docs/VALIDATION.md#4`). 8 Stage B
  worlds touched the domain boundary and 5 carried a discretisation warning;
  they were kept rather than filtered on an outcome-correlated criterion.
* No fireline intensity, no suppression, no diurnal cycle, no moisture.

## 10. Static context is visible and unquantified

Terrain and a coarse fuel class are planner-visible by decision
(`docs/DECISIONS.md#d-006`). Combined with a detection, they narrow the fire's
future by an amount that has **not** been measured. Believed small; not shown.
