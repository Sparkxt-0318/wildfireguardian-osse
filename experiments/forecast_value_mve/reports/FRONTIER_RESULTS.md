# FRONTIER_RESULTS — the break-even analysis

> Synthetic OSSE experiment. Not Korean-anchored. No number here is an
> operational threshold.

The scientific object is the level set `{θ : ΔJ(θ) = 0}` where
`ΔJ = J_forecast − J_baseline`. This report does not assume the set exists, is
connected, is single-valued, or is monotone — and on the final split it is
**not** monotone everywhere.

Source: `../raw_outputs/frontier_stage{B,C}.json`, from
`../raw_outputs/deltas_stage{B,C}.json`.

---

## 1. How a crossing is declared

A cell is **resolved** when its paired world-level bootstrap interval excludes
zero. Brackets are sought between consecutive **resolved** points of opposite
sign, not between adjacent grid points: the cell nearest a crossing is exactly
the cell whose interval is most likely to cover zero, so an adjacency rule
would hide a frontier precisely when the grid brackets it well. A bracket that
spans an unresolved cell is flagged.

Classifications used: `SINGLE_CROSSING`, `MULTIPLE_CROSSINGS`,
`NO_CROSSING_FORECAST_BETTER`, `NO_CROSSING_BASELINE_BETTER`, `UNRESOLVED`.

The intervals are **lightweight diagnostics**, uncorrected across 50 cells.
They mark what the experiment can and cannot see; they are not tests. Formal
uncertainty around the level set belongs to `wildfireguardian-evaluation`.

## 2. Mode A — `CONTROLLED_PERTURBATION`, final split

Verdict: **`FRONTIER_PRESENT`**. 21 of 25 cells resolved; 7 favour the
forecast, 14 the baseline; `all_slices_monotone = false`.

### Across direction error, at fixed latency

| latency | classification | bracket | interpolated | spans unresolved |
|---|---|---|---|---|
| 0 min | `SINGLE_CROSSING` | 10°–35° | ≈ 22.0° | yes |
| 5 min | `SINGLE_CROSSING` | 10°–35° | ≈ 20.8° | yes |
| 15 min | `SINGLE_CROSSING` | 10°–35° | ≈ 17.9° | yes |
| 30 min | `SINGLE_CROSSING` | 0°–20° | ≈ 9.1° | yes |
| 60 min | `NO_CROSSING_BASELINE_BETTER` | — | — | — |

### Across latency, at fixed direction error

| direction error | classification | bracket | interpolated |
|---|---|---|---|
| 0° | `SINGLE_CROSSING` | 30–60 min | ≈ 39 min |
| 10° | `SINGLE_CROSSING` | 15–60 min | ≈ 25 min |
| 20° | `NO_CROSSING_BASELINE_BETTER` | — | — |
| 35° | `NO_CROSSING_BASELINE_BETTER` | — | — |
| 55° | `NO_CROSSING_BASELINE_BETTER` | — | — |

### Reading it

The break-even set in this grid is **a bounded arc, not a line across the
plane**. It runs from about (0°, 39 min) to about (22°, 0 min), and it
**terminates**: beyond roughly 20° of direction error no latency is small
enough, and beyond roughly 40 minutes of latency no accuracy is high enough.
The forecast-favourable region is the corner near the origin, and it is
strictly bounded on both axes.

Every bracket spans one unresolved cell. The interpolated values are therefore
**positions inside a bracket, not point estimates with intervals**, and the
honest statement of the 0-minute row is "the crossing lies between 10° and 35°",
with 22° as the linear interpolate.

**Validation (Stage B) agreed**, with the arc slightly further out: crossings at
≈ 25.2° (0 min), 24.2° (5), 20.7° (15), 19.9° (30) and none at 60 min. That the
final-split arc sits *inside* the validation arc is consistent with the final
archetypes (`ridge_channel`, `plateau_step`) being harder: there the same
direction error costs more.

## 3. Mode B — `INDEPENDENT_MODEL_FORECAST`, final split

Verdict: **`UNRESOLVED_EVERYWHERE`**. 0 of 25 cells resolved.

Every slice classifies as `UNRESOLVED`. There is no crossing to report, and —
this is the part that matters — **there is also no demonstrated absence of
one**. Every point estimate is positive (baseline better, +0.006 to +0.040) and
every interval covers zero.

On the validation split the same surface resolved 11 of 25 cells, all
`NO_CROSSING_BASELINE_BETTER`. Mode B therefore sits right at the edge of what
60 paired worlds can distinguish, and the two splits give the two readings that
a borderline effect gives.

Two further features of the Mode B surface:

* **It is nearly flat.** Injected direction bias moves `ΔJ` by less than 0.02
  across the whole 0°–55° range. The planner's own error already dominates: its
  CSI spans only 0.066–0.133, so a 55° rotation is a small perturbation of an
  already-wrong forecast. The experiment cannot use Mode B to probe the
  direction-error axis, and does not try to.
* **It is not monotone** (`all_slices_monotone = false`), but with nothing
  resolved that is noise, not structure, and is reported as noise.

## 4. Does conventional skill locate the frontier?

No — and this is the cleanest result in the experiment.

| | Spearman ρ(CSI, ΔJ) |
|---|---|
| Mode A, overall | −0.838 |
| Mode A, **within each latency row** | −1.00, −1.00, −1.00, −1.00, −1.00 |
| Mode B, overall | −0.339 |

At fixed latency, CSI orders decision value perfectly. Pooled across latency it
does not, because latency moves value without moving CSI at all: the forecast
field is identical, only its delivery time changes.

The decisive evidence is the equal-skill comparison. On the final split there
are **21 condition pairs with CSI within 0.01 of each other and `ΔJ` differing
by at least 0.05, of which 6 change sign.** The starkest:

| CSI | condition | `ΔJ` | condition | `ΔJ` |
|---|---|---|---|---|
| 1.000 | 0°, 0 min | **−0.136** | 0°, 60 min | **+0.142** |
| 1.000 | 0°, 5 min | −0.126 | 0°, 60 min | +0.142 |
| 1.000 | 0°, 15 min | −0.120 | 0°, 60 min | +0.142 |
| 0.598 | 10°, 15 min | −0.050 | 10°, 60 min | +0.176 |

A forecast that reproduces the hidden arrival-time field **exactly** is worth
0.136 of loss when it arrives immediately and costs 0.142 when it arrives an
hour late. Same field, same CSI, opposite sign.

**Conventional forecast skill was not sufficient to predict decision value
across these worlds.** It is sufficient *conditional on* timeliness. Any
skill-only evaluation of a forecast product would have ranked these five
conditions identically.

## 5. What this does not establish

* Nothing about how often any of these regimes occurs. θ is swept, not
  sampled, and no distribution is placed over it (`../PROTOCOL.md` §7).
* Nothing about degrees or minutes as operational requirements. The grid was
  chosen for this laboratory's 240-minute horizon, 15-minute sensor cadence and
  ~30-minute missions.
* Nothing about Korea.
* Nothing about a different loss. The `unnecessary_dispatch` weight of 0.25 sets
  how much false-alarm cost the experiment charges, and the arc's position
  depends on it. Sensitivity analysis is future work.
* Nothing about a fleet. Feasibility is per mission.

## 6. Artefacts

```
../raw_outputs/deltas_stageC.json     paired ΔJ per condition, with intervals
../raw_outputs/frontier_stageC.json   slice classifications and brackets
../raw_outputs/summary_stageC.json    surfaces, correlations, equal-skill pairs
../figures/fig3_frontier_stageC.png   brackets drawn as bands, no fitted curve
```
