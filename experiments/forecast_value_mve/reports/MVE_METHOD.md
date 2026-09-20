# MVE_METHOD — exact design as executed

Protocol: `../PROTOCOL.md` (version `mve-1.1.0`). Manifests, with git commit and
every version string, are in `../manifests/`. This file records what was
actually run; the protocol records what was promised.

## 1. Pipeline

```text
NATURE WORLD  →  OBSERVATION PROCESS  →  D_s  →  PLANNER/FORECAST
              →  POLICY  →  ACTION/MISSION  →  HIDDEN-WORLD EVALUATION
```

Separation is enforced in code, not by convention: `planner/sandbox.py` seals
hidden truth while any policy or forecast model runs, and `PlannerView.at(s)`
is the only route to observations. Evidence: `LEAKAGE_AUDIT.md`.

## 2. Worlds

| property | value |
|---|---|
| domain | 192 × 192 cells at 30 m = 5.76 km square |
| horizon | 180 min, `dt` = 1 min |
| nature model | 16-direction elliptical front, heterogeneous fuel, terrain, AR(1) wind, optional spotting |
| archetypes | 6, split by geography (development / validation / **final**) |
| Stage B worlds | 60 from the `final` split (`ridge_cross`, `slope_patchy`), `master_seed` 20260920 |

World = `(archetype, terrain, fuels, ignition, weather sequence, nature
randomness)`. Village, routes and residents are **nested** and never counted as
independent units.

**Stage B world audit (n = 60):** 58 threatened (97%), 8 flagged
`boundary_contact`, 5 carrying a discretisation warning, median burned area
395 ha, median 189 detections, median 17 of 17 epochs with a Mode B forecast.

Generation distributions and their evidential status (DATA-INFORMED / ASSUMED /
STRESS-TEST) are in every manifest under `world_generation_audit`. **None is
DATA-INFORMED.** The ignition rule — upwind of the village at 1100 ± 200 m —
is STRESS-TEST and deliberately biases the sample toward threatened villages;
that is why 97% of worlds are threatened, and it is why the
`unnecessary_action` term almost never fires (see `LIMITATIONS.md`).

## 3. Observation process

One generic fire sensor (300 m pixels, 10 min cadence, `p_detect_max` 0.9,
150 m geolocation error, 0.3 false alarms per scan, 4 min nominal latency) and
a 9-station weather network (10 min cadence), with `correlated_outage`
missingness. Four timestamps per record; `D_s` filters on
`availability_time_min` and asserts the filter.

## 4. Forecasts

**Mode A — `CONTROLLED_PERTURBATION`.** Coherent degradation of the hidden
arrival field: directional bias about the ignition, rigid spatial displacement,
optional rate bias and missed spotting. No IID pixel noise. Derived from truth,
so it is a mechanism probe; at zero error and zero latency it is the oracle.

**Mode B — `INDEPENDENT_MODEL_FORECAST`.** A structurally different model using
`D_s` alone: weighted detection centroid, vector-mean persisted wind, a single
analytic ellipse with a **linear** rate law (`r0 + k·U`) and a linear
length-to-breadth law — against nature's power-law rate, heterogeneous fuel,
terrain and spotting. Built inside the planner sandbox, which proves it needs
no truth.

Forecast horizon 90 min. Latency bites by staleness *and* by shrinking the
usable window: a 60-minute-late forecast has 30 minutes of lead left.

## 5. Grid

Mode A sweeps the declared 5 × 5 grid (`none/low/medium/high/severe` ×
`0/5/15/30/60` min). Mode B sweeps **latency only** — its error is not a knob,
so its position on the error axis is *measured* by the skill scores rather than
set. Mode B points are overlaid on the Mode A surface in Figure 1.

## 6. Policies

| policy | role |
|---|---|
| `baseline_tuned_buffer` | **primary baseline**: wind-conditioned trigger/buffer on observed fire state, choosing between routes on current evidence. Tuned on validation: buffer 350 m, time buffer 20 min, wind gain 2.0 |
| `baseline_fixed_buffer`, `baseline_wind_conditioned`, `baseline_fire_blind` | secondary baselines |
| `oracle_reference` | latest feasible order time under perfect knowledge. **Not an executable policy**; a bound only |
| `forecast_aware_feasibility` | **primary forecast-aware policy**: order when the forecast says waiting a safety margin longer loses the mission. Margin tuned on validation and frozen at 90 min |
| `forecast_aware_margin_0` | declared **policy-design sensitivity probe**, not a competitor |

Both the baseline buffer and the forecast-aware margin are tuned on validation
and frozen. Tuning only the baseline would have been an asymmetry in its
favour.

`ACT_NOW` is primary; `WAIT_FOR_FORECAST` is run for two error regimes to price
the cost of waiting.

## 7. Loss

`loss_version` `mve-loss-1.1.0`, declared before the final run:

```
J = 1.00·mission_failed + 0.50·unnecessary_action + 0.30·excess_lead_hours
  + 0.01·responder_exposure_min + 0.001·travel_time_min
```

No mortality, no lives-saved term. Weights were revised **once**, against
measured degeneracy on the development split, and never toward a preferred sign
(`../../../docs/DECISIONS.md#d-017`).

## 8. Missions

Self-evacuation and assisted evacuation are evaluated **in parallel** as
separate capabilities. The inference "no self-evacuation route ⟹ rescue
required" is never made. Mission semantics come from
`PlaceholderDispatchAdapter` (`placeholder-dispatch-0.1.0`) — **not** from
`wildfireguardian-assisted-dispatch`, which was not available. It implements
full edge traversal intervals, pickup duration and coherent scenarios, and
nothing else.

Feasibility is **single-mission** and independent. It is **not** a
fleet-constrained population outcome and is never called a protection rate.

## 9. Execution

| stage | split | worlds | records | runtime |
|---|---|---|---|---|
| benchmarks | development | 16 | — | ~4 min |
| A | development | 12 | 2 040 | 23 s |
| B | **final** | 60 | 10 200 | 130 s |

The final split was evaluated **once**, after the baseline and the policy
margin were frozen. Stage C is scoped but not run (`MVE_READINESS.md`).
