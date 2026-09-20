# LEAKAGE_AUDIT — evidence that the planner did not see hidden truth

The claim is narrow and testable: **no policy or forecast model in this
experiment could read the nature seed, future fire state, future weather,
future spotting, the final perimeter, future observations, or any
evaluator-only quantity.**

## 1. Enforcement, not convention

| mechanism | where | what it does |
|---|---|---|
| `SealedTruth` | `planner/sandbox.py` | wraps hidden truth; **every** attribute access raises `TruthAccessViolation` inside a planner sandbox |
| `planner_sandbox()` | `planner/sandbox.py` | the decision loop and Mode B forecast construction both run inside it |
| `assert_evaluator_context()` | `planner/sandbox.py` | guards each function that legitimately reads truth (Mode A construction, skill scoring, threat time, decision evaluation) — they raise if reached from planner code |
| `PlannerView.at(s)` | `planner/view.py` | the only route to observations; filters on `availability_time_min` and **asserts the result** rather than trusting the filter |
| `build_planner_view` | `planner/view.py` | copies only the three planner-visible tables; the detection ledger, true sensor state and generative parameters are not carried over, so they cannot be reached even by accident |
| `Forecast.__post_init__` | `planner/forecast.py` | rejects a forecast available before issue, or valid before issue (a current-state estimate is not a forecast) |
| `run_policy` | `policies/base.py` | raises if a forecast handed to a policy is not yet available at that epoch |

## 2. Tests that back each claim

All in `tests/test_planner_separation.py` unless noted.

| claim | test |
|---|---|
| Truth is unreachable from planner code | `test_sealed_truth_is_transparent_outside_and_opaque_inside` |
| The seal survives exceptions | `test_sandbox_state_is_restored_after_an_exception` |
| Truth-reading functions refuse to run in a sandbox | `test_evaluator_only_functions_refuse_to_run_in_a_sandbox` |
| The independent model needs no truth at all | `test_the_independent_model_needs_no_truth_at_all` (built *inside* the sandbox) |
| Skill scoring is evaluator-only | `test_skill_scoring_is_evaluator_only` |
| `D_s` never returns an unavailable record | `test_planner_view_returns_only_available_records` |
| A late-processed record stays unavailable | `test_a_record_processed_late_is_unavailable_until_delivered` |
| No seed is reachable from the planner view | `test_no_seed_value_is_reachable_from_the_planner_view` |
| The view holds no truth reference | `test_planner_view_holds_no_truth_reference` |
| Forecast latency is exactly as configured | `tests/test_forecast_modes.py::test_latency_is_exactly_the_configured_delay` |
| A current-state estimate is rejected as a forecast | `tests/test_forecast_modes.py::test_a_current_state_estimate_is_not_a_forecast` |
| Every policy is scored on the same worlds | `tests/test_experiment.py::test_every_policy_is_scored_against_the_same_worlds` |
| Tuning on the final split is refused | `tests/test_experiment.py::test_tuning_refuses_the_final_split` |
| Swept values never reach planner-visible identifiers | `tests/test_experiment.py::test_planner_visible_identifiers_carry_no_swept_value` |
| Every exported row carries provenance | `tests/test_experiment.py::test_every_row_carries_full_provenance` |

The runner additionally re-checks the hidden arrival field's fingerprint after
every world and raises if it changed during evaluation — policies cannot
mutate the world they are being scored on.

The repository-level leakage scanner (`wg-osse validate`) continues to run over
generated worlds: forbidden field names, seed values, truth rasters,
real-instrument names and swept values in planner-visible identifiers.

## 3. What this audit does **not** claim

* **Mode A is derived from hidden truth by construction.** It is a mechanism
  probe, not a leakage-safe planner, and at zero error with zero latency it
  *is* an oracle. It is labelled `CONTROLLED_PERTURBATION` in every record, and
  the conclusions that matter lean on Mode B. Reading a Mode A row as "what a
  real forecast would do" is the single easiest way to misuse this experiment.
* **The oracle reference reads truth on purpose.** It is a bound, never an
  executable policy, and is labelled `oracle_reference`.
* **Informative missingness is an open channel.** Under `fire_correlated`
  missingness the *absence* of data correlates with the hidden fire. Stage B
  used `correlated_outage`, which does not have this property, but the channel
  exists in the laboratory and is not closed by anything above.
* **Static context is planner-visible by decision** — terrain and a coarse fuel
  class (`docs/DECISIONS.md#d-006`). They carry no temporal information, but a
  consumer combining them with a detection narrows the fire's future by an
  amount this repository has **not** measured (`../../../tasks/CURRENT.md`).
* **These tests show the paths that were checked were closed.** They cannot
  show that no other path exists.
