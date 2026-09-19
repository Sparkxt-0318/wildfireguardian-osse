# SCOPE

## In scope

* Synthetic landscape generation (elevation, slope/aspect, heterogeneous fuels).
* Synthetic weather generation (wind speed/direction time series, temperature,
  relative humidity) — spatially uniform in v1.
* A transparent synthetic fire-spread nature model producing a **fire arrival
  time field** with anisotropic, wind-dependent, slope-dependent,
  fuel-dependent spread and optional stochastic spot ignition.
* A configurable **observation process** producing:
  * generic fire-detection streams (cadence, latency, geolocation noise,
    detection probability, false negatives, optional false positives);
  * generic weather-station streams (station count/placement, measurement
    error, latency, missingness).
* Explicit four-stage observation time semantics
  (event / acquisition / processing / availability).
* Missingness models: MCAR, temporally correlated outage, fire-correlated
  sensor failure.
* Deterministic, seed-derived reproduction.
* Incremental, crash-safe per-world storage with manifests and checksums.
* Leakage, timing, determinism and qualitative-behaviour validation.
* A CLI: `wg-osse generate | validate | summarize` (plus `scenarios`, `selftest`).

## Out of scope (hard boundaries)

These are **not** to be added to this repository. If a task appears to require
one, stop and record it in `tasks/CURRENT.md` instead of implementing it.

| Out of scope | Why |
|---|---|
| Routing / road-network exposure | Belongs to the routing repository. Importing it here would couple the OSSE to a consumer. |
| Evacuation or rescue outcome models | Same. Also requires behavioural assumptions this repo cannot validate. |
| Forecast-value / decision-value analysis | The OSSE must be usable by *any* evaluation method; embedding one biases the lab. |
| Real observational data ingestion | Would reintroduce the missing-counterfactual problem the OSSE exists to avoid. |
| Named real sensors (e.g. any specific satellite instrument) | Specifications have not been verified here. See `docs/DECISIONS.md#d-002`. |
| Operational fire forecasting claims | The nature model is explicitly not an operational model. |
| CFD, WRF-SFIRE, or any coupled fire–atmosphere solver | Phase 1 requires transparency and speed, not fidelity. See `docs/DECISIONS.md#d-003`. |
| Network calls at generation time | Reproducibility. Generation is pure-local and offline. |
| Integration with another WildfireGuardian repository | Explicitly deferred; see `tasks/ROADMAP.md`. |

## Dependency policy

Runtime dependencies are limited to `numpy` and `PyYAML`. Tests additionally use
`pytest`. Outputs use `.npy`, `.csv` and `.json` only, so that a consumer needs
no library from this repository to read a world.

## Interpretation limits

Results obtained in this laboratory are statements about the **synthetic
system defined in `docs/NATURE_MODEL.md` and `docs/OBSERVATION_MODEL.md`**.
Transfer to real wildfire operations requires separate evidence that is
**not** produced here. Any downstream document quoting a number from this
repository must carry that caveat.
