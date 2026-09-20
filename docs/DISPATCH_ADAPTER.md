# DISPATCH_ADAPTER

The contract an external dispatch package must satisfy to supply mission
feasibility to the forecast-value experiment, and what the temporary internal
placeholder does in the meantime (`docs/DECISIONS.md#d-018`).

## 1. Why a contract and not an implementation

`wildfireguardian-assisted-dispatch` owns these semantics. This repository must
not import another WildfireGuardian repository (`docs/DECISIONS.md#d-001`), and
reimplementing its full `base → resident → pickup → destination` logic here
would create precisely the coupling that rule exists to prevent.

So the experiment depends on a **protocol**, not on a class. The placeholder is
labelled `INTERNAL_PLACEHOLDER_V1` in every exported record, so no result can
be mistaken for one produced with assisted-dispatch semantics.

## 2. The contract

```python
class MissionFeasibilityAdapter(Protocol):
    adapter_id: str

    def plan_and_evaluate(
        self, village, hazard, resident_id, dispatch_time_min, horizon_min
    ) -> MissionOutcome: ...

    def evaluate_plan(self, village, hazard, plan) -> MissionOutcome: ...
```

Required properties:

1. **Pure function of its arguments.** No access to the laboratory's `truth/`
   directory, and no access to the information time. The *caller* decides which
   hazard field is legitimate; the adapter never decides what the planner is
   allowed to know.
2. **One hazard type.** `ArrivalTimeHazard` wraps a raster of arrival times.
   The same class wraps hidden truth (evaluation) and a forecast (planning).
   Which one an adapter holds is a property of the caller. This is what keeps a
   scenario *coherent*: the planner's feasibility question and the evaluator's
   are the same question, answered by different fields.
3. **`evaluate_plan` must not re-plan.** A plan formed under a forecast is
   replayed against hidden truth unchanged. This is the paired-world workhorse;
   an adapter that silently re-routed would destroy the contrast.
4. **Full edge traversal interval.** An edge is unusable for a traversal over
   `[t_enter, t_exit]` if any corridor point burns at any time in that interval,
   including behind the vehicle. `POINT_IN_TIME` is available and is strictly
   weaker; `FULL_INTERVAL` is the contract default.
5. **Explicit pickup duration** at the resident, during which the resident must
   remain reachable.
6. **Non-monotone feasible dispatch windows must be representable.** Nothing in
   the contract may assume that dispatching earlier is always at least as good:
   the chosen route can change with the dispatch time, and the feasible set is
   not required to be an interval.
7. **Failure taxonomy before blame.** When the fire has already reached the
   resident, that must be reported as
   `FIRE_REACHED_RESIDENT_BEFORE_PICKUP_COMPLETE`, not as a routing failure —
   "no route to the resident" is then true but useless, and the failure analysis
   depends on the distinction.

## 3. What the placeholder implements

* time-dependent Dijkstra on earliest feasible arrival (constant edge travel
  times, so the network is FIFO and plain Dijkstra is exact);
* the mission shape, the pickup, and the two-leg structure;
* self-evacuation evaluated **separately**, at its own speed, and gated on a
  declared capability rather than on route existence;
* exposure as a modelled proxy: the fraction of corridor sample points already
  burned at entry, times the traversal duration. Not a dose model.

## 4. What the placeholder does *not* implement

* finite responder fleets — every mission is evaluated independently
  (`INDEPENDENT_SINGLE_MISSION_FEASIBILITY`), so no result may be called a
  population or system protection rate;
* replanning after dispatch;
* vehicle- or crew-specific constraints, refusal behaviour, or road capacity;
* any behavioural model of residents.

## 5. Replacing it

Construct the external adapter and pass it to `policy.base.run_policy` and to
the policies' `adapter` field. The experiment imports nothing from
`dispatch.PlaceholderDispatchAdapter` except as a default. After replacement,
re-run the constructed benchmarks (`wg-fv benchmarks`) before re-running any
stage: the benchmark set is what shows the new semantics still express the
regimes the research question is about.
