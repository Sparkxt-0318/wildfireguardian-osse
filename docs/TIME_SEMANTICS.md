# TIME_SEMANTICS

This distinction is **mandatory**. Collapsing these four times into one is the
most common way an OSSE silently becomes a look-ahead oracle.

## 1. The four times

Every observation record carries all four, in minutes since scenario `t0`:

| Time | Symbol | Definition |
|---|---|---|
| **Physical event time** | `event_time_min` | the instant of the world state that the observation is about. For a fire scan, the scan instant; for a weather reading, the instant sampled. |
| **Acquisition time** | `acquisition_time_min` | the instant the sensor finished recording it. `>= event_time_min` (0 offset for an instantaneous sensor; positive for an integrating one). |
| **Processing time** | `processing_time_min` | the instant the derived product existed. `>= acquisition_time_min`. |
| **Availability time** | `availability_time_min` | the instant the record became usable by a consumer. `>= processing_time_min`. |

```text
 event ──► acquisition ──► processing ──► availability
   │            │               │               │
 world       sensor          product        delivery
 state       readout         generated      completed
```

## 2. The usage rule

> **An observation may be used only at or after its `availability_time_min`.**

A consumer making a decision at time `t` may use exactly

```python
obs[obs.availability_time_min <= t]
```

and nothing else. Filtering on `event_time_min` instead is a bug that produces
optimistic results; it is the single most important thing a downstream
repository must get right. `storage/reader.py` provides
`available_at(df, t)` so that no consumer has to write the comparison itself.

## 3. How the offsets are generated

```
acquisition_time  = event_time       + acquisition_offset_min
processing_time   = acquisition_time + processing_latency_min + jitter_p
availability_time = processing_time  + delivery_latency_min   + jitter_d
```

All four components are constrained non-negative:
`acquisition_offset_min >= 0`, both latencies `>= 0`, and jitters are drawn from
a **non-negative** distribution (`Exponential(mean = jitter_mean_min)`, i.e.
latency jitter can only ever make a product later). Therefore the ordering

```
event <= acquisition <= processing <= availability
```

holds **by construction**, not by convention. It is additionally asserted at
record-construction time (`timeline.ObservationTimes.__post_init__`) and tested
(`tests/test_timing.py`).

Latency jitter is drawn from the `sensor_seed` stream.

## 4. Wall-clock time

`epoch` (UTC, ISO-8601) in the scenario config maps simulation minutes to
timestamps:

```
utc(t) = epoch + timedelta(minutes=t)
```

Wall-clock columns (`event_time_utc`, `availability_time_utc`) are
**presentational**. All logic uses the float minute columns. There is no
timezone or DST handling and no diurnal cycle in v1
(`docs/ASSUMPTIONS.md#F`).

## 5. Simulation time vs observation time

The nature model steps on a fixed `dt` (default 1 min). Observation cadences are
independent of `dt` and need not be multiples of it; a scan time is snapped to
the nearest simulation step when sampling the active set, and the *reported*
`event_time_min` is the **snapped** time — the consumer is told the time of the
state actually sampled, not an idealised one.

## 6. Horizon and truncation

A scenario has a horizon `t_end`. Observations are generated for scans with
`event_time_min <= t_end`. Their `availability_time_min` may exceed `t_end`;
such records are kept (a consumer at `t <= t_end` correctly cannot use them) and
are counted in the summary as `n_unavailable_within_horizon`.

Because every observation depends only on the world at times `<= event_time_min`,
truncating the simulation cannot change any observation that was already
available:

> simulate to `H₁ < H₂`; every observation with
> `availability_time_min <= H₁` is **bit-identical** between the two runs.

This is the prefix-causality property and it is tested directly
(`tests/test_causality_prefix.py`). It is the strongest single guarantee in this
repository that no observation contains future information.
