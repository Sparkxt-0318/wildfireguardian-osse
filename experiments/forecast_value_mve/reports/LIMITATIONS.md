# LIMITATIONS — what remains artificial

> Synthetic OSSE experiment. Nothing here is Korean-anchored.

Ordered by how much each one limits interpretation, most limiting first. A
limitation that is also an *open question* is marked; those are the ones that
could change a conclusion rather than merely narrow it.

---

## 1. The nature model is not a wildfire model — **open**

Elliptical anisotropic front propagation over a synthetic rate-of-spread
raster. It is transparent, fast, reproducible and different from the planner,
which is what an OSSE nature model must be. It is not calibrated: the spread
coefficients are `UNKNOWN` in the laboratory's own terms
(`docs/ASSUMPTIONS.md#C-07`). No number here transfers to a real fire.

The laboratory's own carried-forward limits apply unchanged: spatially uniform
wind (`#B-01`), and a 16-direction stencil whose usable wind range tops out
near 6 m·s⁻¹ (`docs/VALIDATION.md#4`), which is why the sweep stops there. The
experiment therefore says nothing about high-wind regimes — exactly the regimes
where forecast value is most contested.

## 2. Mission feasibility is a labelled placeholder — **open**

`INTERNAL_PLACEHOLDER_V1`, not `wildfireguardian-assisted-dispatch`. It carries
the mission shape, full-interval traversal semantics, the pickup duration and
one hazard-field type, and nothing else (`docs/DISPATCH_ADAPTER.md`). No result
here may be described as using assisted-dispatch semantics. Replacing it is a
one-class change and the benchmarks must be re-run afterwards.

## 3. No responder resource constraint

Every mission is evaluated independently of every other:
`INDEPENDENT_SINGLE_MISSION_FEASIBILITY`. Six simultaneous dispatches in one
world cost six units of `resource_use` but never contend for a vehicle or a
crew. **No number in this experiment is a system or population protection
rate**, and the phrase does not appear. Finite fleets must be modelled before
any population-level policy claim.

## 4. No probability distribution over the error space — **by choice**

θ is swept, not sampled. There is no basis for a prior over forecast direction
error or product latency, so none is invented. Every result is conditional:
"under this error regime, X". A reader who wants an expected value over
realistic forecast errors cannot get it from this experiment, and should not
construct one by weighting these cells with a guess.

## 5. One commitment per resident; no replanning

A mission is planned once and never revised, even when the next forecast
arrives mid-mission and contradicts the one it was planned under. Real dispatch
replans. This makes both policies worse than they could be; whether it makes
them *equally* worse is not established, and a forecast-aware policy plausibly
loses more from it — it is the one with new information arriving.

## 6. Waiting is modelled, replanning-while-waiting is not

`WAIT_FOR_FORECAST` costs real decision time and can destroy options, which is
the important half. But a policy that waits cannot partially commit, stage
assets forward, or warn a resident; its only alternatives are act and wait.
Tuning chose not to wait at all, so this limitation is currently not binding —
but it would become binding under any change that makes waiting attractive.

## 7. Terrain-independent village and road geometry

A perturbed lattice, placed without reference to the terrain it sits on. Real
rural Korean settlements sit in valleys and their roads are dendritic, with far
fewer alternative paths. A lattice is more forgiving: it offers reroutes that a
dendritic network would not, which plausibly *understates* how often fire
closes the only road. Classified `ASSUMED` in the generation audit.

## 8. The ignition distribution is conditioned on the village

Ignitions are placed upwind of the village at 1400–3000 m. Both policies face
the same distribution and neither uses a prior, so this is not leakage
(LEAKAGE_AUDIT.md §5a) — but the world population is a designed one, chosen so
that the fire-to-village race is decidable within the horizon. It is not a
sample from anything.

## 9. Static context may narrow the future by an unmeasured amount — **open**

Terrain and coarse fuel class are planner-visible
(`docs/DECISIONS.md#d-006`). How much they narrow the fire's future, combined
with one detection, is believed small and is **not measured**. Mode B ignores
terrain entirely and uses fuel class only through its own miscalibrated
mapping, which bounds the exploitation by *this* planner but not by a future
one. Inherited from the laboratory's open questions.

## 10. A single planner, a single baseline family, a single loss

One Mode B planner (`docs/DECISIONS.md#d-019`), whose specific blind spots
drive its specific errors — a planner with a slope term would produce a
different surface. One baseline family (trigger/buffer), tuned. One loss, with
weights declared and never varied; sensitivity analysis is future work, and
the `unnecessary_dispatch` weight of 0.25 in particular sets how much
false-alarm cost the experiment charges.

## 11. Informative missingness is present but unquantified

`fire_correlated` sensor failure exists in the laboratory and is deliberate.
This experiment uses MCAR at `p = 0.05` only, so the effect of *informative*
absence on decision value is untested here. The laboratory's own open question
about how much a consumer could learn from an absence pattern remains open.

## 12. Diagnostics are not inference

The paired bootstrap used to mark cells "resolved" or "unresolved" is a
lightweight diagnostic with no multiplicity correction across 25 cells × 2
modes. With 50 cells, several "resolved" cells are expected by chance alone.
Formal inference belongs to `wildfireguardian-evaluation`; the exported rows
are the handoff, and the per-cell resolution flags here must not be read as
tests.

## 13. Determinism is per-environment

Inherited from `docs/DECISIONS.md#d-012`: reproduction is guaranteed on the
same platform and numpy version, not across platforms.

---

## What would have to change before a Korean claim

See `MVE_READINESS.md` §7. In short: a Korean DEM, a Korean fuel map, real road
networks, Korean weather-regime distributions and Korean village archetypes —
and then the generic and Korean-anchored results reported **separately**, never
merged.
