# OBSERVATION_MODEL

The observation process is the **only** channel from hidden truth to a consumer.
Everything a consumer is allowed to see is produced by the operators described
here, and every degradation is a named parameter.

```text
HIDDEN NATURE WORLD  ──►  OBSERVATION PROCESS  ──►  AVAILABLE OBSERVATIONS
   truth/                  sampling · masking          observations/
                           noise · delay · loss
```

## 0. Visibility contract

Every file written for a world carries a **visibility label** in
`manifest.json`: `hidden` or `planner_visible`.

* Everything under `truth/` is `hidden`. No consumer may read it while acting as
  a planner; it exists for scoring and for post-hoc analysis.
* Everything under `observations/` is `planner_visible`.
* `metadata/` is `planner_visible` and contains only identifiers and geometry —
  never a nature parameter, never a seed (see §6).

The labels are checked mechanically: `wg-osse validate <world>` fails if a
planner-visible file contains a forbidden field name or a forbidden value.

## 1. Generic sensors only

No sensor here is named after or parameterised from a real instrument
(`docs/DECISIONS.md#d-002`). A sensor is *only* its behavioural parameters. The
validator rejects sensor ids or labels that match known real-instrument names.

## 2. Fire observation stream

### 2.1 Sampling

A fire sensor has a pixel size `p` (an integer multiple of the nature cell size
`dx` is not required; the nature grid is aggregated into `⌈n·dx/p⌉` blocks) and
scans at

```
t_s = first_scan_offset_min + s · cadence_min ,   s = 0, 1, 2, …
```

At scan time `t_s` the sensor sees the **actively burning set** `A(t_s)`
(`docs/NATURE_MODEL.md#1`) — never `B(t_s)`, never anything at `t > t_s`.
For each sensor pixel `P`:

```
a(P) = (number of cells of A(t_s) in P) · dx²      [m²]
```

### 2.2 Detection probability and false negatives

```
p_det(P) = p_detect_max · ( 1 − exp( − a(P) / detect_ref_area_m² ) )
detected ~ Bernoulli( p_det(P) )
```

A pixel with fire that is not detected is a **false negative**; the mechanism is
the Bernoulli draw itself, so the false-negative rate is `1 − p_det`, controlled
through `p_detect_max` and `detect_ref_area_m2`. Pixels with `a(P) = 0` are never
detected by this operator (they can still be produced as false positives, §2.4).

### 2.3 Geolocation noise

A detected pixel reports a position

```
(x̂, ŷ) = (x_P, y_P) + N(0, geoloc_sigma_m² I₂)
```

where `(x_P, y_P)` is the pixel centre. The reported position is *not* clipped
to the pixel and may fall outside the domain; that is a real failure mode and is
left in.

### 2.4 False positives (optional)

```
N_fp ~ Poisson( false_positive_rate_per_scan )
```

placed at uniformly random positions in the domain. **False positives are
unlabelled in the planner-facing file** (`docs/DECISIONS.md#d-007`); the ledger
of which detections were spurious is in `truth/detection_ledger.csv`.

### 2.5 Scan log

Every scan is written to `observations/fire_scan_log.csv`, including scans with
zero detections and scans suppressed by an outage
(`status ∈ {ok, outage}`). Without it, "no detections" would be ambiguous
between *not observed* and *observed as empty* (`docs/DECISIONS.md#d-008`).

### 2.6 Planner-facing schema — `observations/fire_detections.csv`

| column | meaning |
|---|---|
| `obs_id` | unique id, stable across reruns |
| `sensor_id` | generic sensor identifier |
| `event_time_min` | physical time of the observed state (= scan time) |
| `acquisition_time_min` | time the sensor recorded it |
| `processing_time_min` | time the product was produced |
| `availability_time_min` | **earliest legal use time** |
| `event_time_utc`, `availability_time_utc` | ISO-8601, derived from `epoch` |
| `x_m`, `y_m` | reported position (noisy) |
| `pixel_size_m` | nominal footprint of the report |
| `geoloc_sigma_m` | **nominal, published** geolocation uncertainty |
| `confidence` | coarse 3-level ordinal (`low`/`nominal`/`high`) |

`geoloc_sigma_m` is a *published sensor specification*, not a hidden parameter —
a real product ships its stated accuracy. `p_detect_max`,
`detect_ref_area_m2`, `false_positive_rate_per_scan` and every missingness
parameter are **hidden** and live in `truth/observation_params.json`.

## 3. Weather observation stream

Stations are placed (grid, random or explicit) with known positions published in
`observations/station_metadata.json` — a station's location is legitimately
known. Each station samples the true weather at its cadence and reports

```
Û     = max(0, U + N(0, σ_speed²))
θ̂_w  = θ_w + N(0, σ_dir²)                 (wrapped to [0, 2π))
T̂    = T + N(0, σ_temp²)
RĤ   = clip(RH + N(0, σ_rh²), 0, 100)
```

Because wind is spatially uniform in v1 (`docs/ASSUMPTIONS.md#B-01`), stations
differ only through their independent noise, their cadence phase and their
missingness — not through position. This is a known limitation and is the first
item in `tasks/ROADMAP.md`.

Schema — `observations/weather_station_obs.csv`: `obs_id, station_id`, the four
time columns, `event_time_utc`, `availability_time_utc`, `wind_speed_ms`,
`wind_dir_deg`, `temp_c`, `rh_pct`, plus the published nominal error
specifications `sigma_speed_ms`, `sigma_dir_deg`.

## 4. Missingness

Applied to both streams, selected by an explicit scenario mode.

| mode | mechanism | parameters |
|---|---|---|
| `none` | nothing is dropped | — |
| `mcar` | each record dropped independently | `p_missing` |
| `correlated_outage` | two-state Markov chain per sensor on a fixed tick; all records in the `down` state are dropped | `p_fail`, `p_repair`, `tick_min` |
| `fire_correlated` | a station/sensor fails with hazard `λ_fire` per minute while the fire is within `fail_radius_m` of it, then stays down for `down_duration_min` (`inf` = permanent) | `fail_radius_m`, `lambda_fire_per_min`, `down_duration_min` |

All missingness randomness comes from the `missingness_seed` stream, so the
missingness pattern can be varied while holding the *measurement* noise fixed,
and vice versa.

**`fire_correlated` is informative missingness.** No truth value is written
anywhere planner-visible, so it is not leakage, but the *pattern of absence*
carries information about the hidden fire and a consumer could exploit it. This
is intentional and is flagged in `docs/FAILURE_MODES.md#F-05` and
`docs/DECISIONS.md#d-009`. Scenarios that must avoid it use `mcar`.

For a fire sensor, a `down` interval suppresses the whole scan and is published
as `status = outage` in the scan log; individual detections are not silently
dropped one by one, because a real sensor outage is not per-pixel. For weather
stations, `mcar` drops individual records (a telemetry gap) while
`correlated_outage` and `fire_correlated` drop contiguous runs.

## 5. Storage layout

```text
world_000001/
    truth/
        arrival_time_min.npy        # +inf where never burned
        burned_mask_final.npy
        active_area_series.csv      # burned/active area vs time
        landscape/{elevation_m,fuel_multiplier,fuel_class}.npy
        weather_true.csv
        ignitions.json              # initial + every spotting attempt
        nature_params.json          # every hidden parameter, incl. seeds
        observation_params.json     # hidden sensor/missingness parameters
        detection_ledger.csv        # which detections were real vs spurious
        sensor_state.csv            # true up/down intervals per sensor
        world_summary.json          # aggregate stats (burned area, latencies)
    observations/
        fire_detections.csv
        fire_scan_log.csv
        weather_station_obs.csv
        station_metadata.json
        sensor_specs_published.json # nominal specs only
        static_context/{elevation_m,fuel_class}.npy
    metadata/
        world_metadata.json         # ids, geometry, time window, code version
    manifest.json                   # inventory + sha256 + visibility labels
```

`manifest.json` is a **pure inventory**: paths, sizes, checksums, visibility
labels, flags and warnings. It deliberately contains no aggregate truth and no
seed, so the access rule inside a world is exactly: *a planner may read
`observations/` and `metadata/`, and nothing else.* Per-world aggregate
statistics live in `truth/world_summary.json`, and the batch-level
`batch_index.jsonl` (outside any world) mirrors them for `wg-osse summarize`;
both are experimenter-facing.

`observations/static_context/` is planner-visible by explicit decision
(`docs/DECISIONS.md#d-006`): terrain and a coarse fuel class are known before an
incident and carry no temporal information. The continuous `fuel_multiplier`
used by the model is **not** exposed — it is a model parameter.

## 6. What a planner-facing file must never contain

* fire state at any time later than the record's own `event_time_min`;
* the arrival-time field, the final perimeter or any burned mask;
* the ignition point or any spot-ignition event;
* true wind at any time (past or future) — only station measurements;
* any hidden nature or observation parameter (`spread_multiplier`, `R0_base`,
  `a_w`, `p_detect_max`, `lambda_fire_per_min`, …);
* any seed, at all;
* any label identifying a detection as a false positive, or a gap as
  fire-correlated.

This list is executable: it is the forbidden-key set in
`validation/leakage.py`, and it is enforced by `tests/test_no_leakage.py` plus
the prefix-causality test in `tests/test_causality_prefix.py`.
