# MVE_RESULTS — what happened

Stage B, **final** split, 60 worlds, evaluated once after protocol freeze.
Records: `../raw_outputs/evaluation_records_mve_stage_b.csv` (10 200 rows).
Figures: `../figures/`.

> Synthetic OSSE worlds. **Not Korean-anchored.** Every number is conditional
> on the declared loss (`mve-loss-1.1.0`), the declared error regimes, and the
> placeholder dispatch semantics. No probability is assigned to error regimes,
> so these are conditional statements, not expectations.

Unless stated, numbers are **self-evacuation**, mean `J` over the 60 paired
worlds. Lower is better.

## 1. Baselines and the bound

| policy | mean J | failure rate | ordered |
|---|---|---|---|
| `baseline_fixed_buffer` | **0.237** | 0.067 | 1.00 |
| `baseline_wind_conditioned` | 0.252 | 0.100 | 1.00 |
| `baseline_tuned_buffer` *(primary)* | 0.267 | 0.117 | 1.00 |
| `baseline_fire_blind` | 0.405 | 0.317 | 1.00 |
| `oracle_reference` *(bound, not a policy)* | 0.043 | 0.017 | 0.98 |

**The tuned baseline is not the best baseline on the held-out split.** It was
tuned on validation (mean J 0.354 there) and came third on final, behind the
simpler fixed buffer by 0.030. That is ordinary generalisation gap, and it
matters for reading everything below: `ΔJ` is measured against the *primary*
baseline, so a comparison against the *best* baseline would be about **0.03
less favourable** to every forecast-aware row. Where that changes a conclusion,
it is said so explicitly.

The oracle at 0.043 against a baseline at 0.267 says the decision problem has
real headroom: roughly 0.22 of loss is reachable by better timing alone.

## 2. Forecast-aware policy, controlled perturbation (Mode A)

Mean `J`, tuned policy (90 min safety margin):

| error \ latency | 0 | 5 | 15 | 30 | 60 |
|---|---|---|---|---|---|
| none | **0.124** | 0.126 | 0.207 | 0.229 | 0.267 |
| low | 0.150 | 0.151 | 0.207 | 0.229 | 0.267 |
| medium | 0.163 | 0.140 | 0.231 | 0.245 | 0.267 |
| high | 0.251 | 0.180 | 0.229 | 0.245 | 0.267 |
| severe | 0.334 | 0.345 | 0.310 | 0.297 | 0.267 |

Read against the baseline's 0.267 (Figure 2 shows `ΔJ` directly):

* A **prompt** forecast helps at every error level except `severe`.
* At **60 min latency every cell equals the baseline exactly.** The forecast
  arrives after the policy has already acted, so it changes nothing at all.
  This is the `ACCURATE_BUT_LATE` benchmark appearing in the main experiment,
  not just in the benchmark suite.
* `severe` error at low latency is **worse** than doing without a forecast.

## 3. The independent model (Mode B) — the mode that matters

| latency | mean J | ΔJ vs tuned baseline | failure rate | mean CSI |
|---|---|---|---|---|
| 0 | 0.228 | **−0.039** | 0.067 | 0.121 |
| 5 | 0.230 | −0.037 | 0.067 | 0.151 |
| 15 | 0.237 | −0.030 | 0.100 | 0.190 |
| 30 | 0.249 | −0.018 | 0.100 | 0.239 |
| 60 | 0.267 | 0.000 | 0.117 | 0.285 |

A genuinely independent, structurally different model **beats the tuned
baseline when prompt**, by a small margin that decays to exactly zero by 60
minutes of latency. Measured against the *best* baseline (0.237) the prompt
advantage is 0.009 — within noise. **The honest statement is that Mode B is
about as good as a well-tuned buffer, and no better, under this loss.**

Mode B's CSI *rises* with latency (0.12 → 0.29). That is not the model
improving: later forecasts are issued from more observations and scored over a
shorter remaining window. It is a caution about reading skill across
conditions.

## 4. Skill does not determine value (Figure 1)

The clearest result in the experiment:

| condition | mean CSI | ΔJ |
|---|---|---|
| Mode B, latency 0 | 0.121 | **−0.039** (better than baseline) |
| Mode A `severe`, latency 0 | 0.107 | **+0.067** (worse than baseline) |

Two forecasts of **essentially the same conventional skill**, opposite signs of
decision value. Conversely at CSI = 1.0 (a perfect forecast) `ΔJ` ranges from
−0.225 to 0.000 depending only on latency and on how the forecast is used.

**Conventional forecast skill was not sufficient to explain decision value
across these worlds.** This is the answer to the question the brief asked not
to assume.

## 5. How the forecast is used matters more than how good it is

| condition | tuned policy (margin 90) | aggressive probe (margin 0) |
|---|---|---|
| perfect, latency 0 | 0.124 | **0.042** (≈ oracle 0.043) |
| medium error, latency 0 | 0.163 | 0.527 |
| severe error, latency 0 | 0.334 | 0.751 |

Used aggressively, a *perfect* forecast recovers essentially the whole oracle
bound — and a *medium* one doubles the baseline's loss. Used conservatively,
the same forecasts give a smaller gain and a much smaller downside. The
aggressive policy acts at the exact feasibility boundary the forecast draws,
which is the most error-sensitive point available.

## 6. Waiting is not free

`WAIT_FOR_FORECAST` versus `ACT_NOW`, same policy and conditions:

| error regime | ACT_NOW | WAIT | mean order time |
|---|---|---|---|
| none | 0.191 | 0.207 | 40.5 → 44.1 min |
| medium | 0.210 | 0.225 | 40.5 → 44.0 min |

Waiting one epoch for a fresher forecast delayed action by ~3.6 minutes and
cost ~0.016 of loss. Small, consistent, and in the direction the protocol
predicted: the fire does not pause while the policy deliberates.

## 7. Assisted evacuation is a harder problem

| policy | self-evacuation | assisted |
|---|---|---|
| tuned baseline | 0.267 | 0.560 |
| forecast-aware, perfect, latency 0 | 0.124 | 0.392 |
| oracle | 0.043 | 0.307 |

Assisted missions must first bring a responder from the base and then dwell for
a pickup, so their feasible windows are shorter and close earlier. Every
qualitative conclusion above holds for both, with larger absolute losses for
assisted. The two are reported separately and **never** combined into a single
"protected" figure.

## 8. Benchmark validation

All five constructed benchmarks are `DEMONSTRATED`
(`../raw_outputs/benchmark_validation.json`): `ACCURATE_BUT_LATE`,
`CRUDE_BUT_TIMELY`, `FORECAST_HARM`, `BASELINE_MATCH`,
`SIMILAR_SKILL_DIFFERENT_VALUE`. `FORECAST_HARM` is demonstrated by the
aggressive probe; the frozen policy does not exhibit it at any tested error
level. These are validation cases showing the apparatus can express each
phenomenon — **not evidence about how common any of them is.**

## 9. Negative and unflattering results, reported

* The tuned baseline lost to a simpler fixed buffer on the held-out split.
* Against that best baseline, the independent model's advantage is within
  noise: **no clear win for forecast-aware action from the realistic mode.**
* No break-even frontier exists for the frozen policy (`FRONTIER_RESULTS.md`).
* Latency of 60 minutes reduces every forecast to exactly no effect.
* 97% of worlds were threatened, so the experiment barely tests false alarms
  (`LIMITATIONS.md`).
