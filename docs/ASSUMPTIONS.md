# ASSUMPTIONS

Every entry is either **SYNTHETIC** (a freely chosen parameter of the synthetic
world, not claimed to match reality), **STRUCTURAL** (a modelling simplification)
or **UNKNOWN** (a real-world quantity we have not verified and therefore refuse
to guess).

## A. Landscape

| ID | Assumption | Class |
|---|---|---|
| A-01 | The domain is a flat-projected regular square raster; no map projection or earth curvature is modelled. Coordinates are local metres with an arbitrary origin. | STRUCTURAL |
| A-02 | Cell size (default 30 m) is a configuration choice, not a claim about any real product's resolution. | SYNTHETIC |
| A-03 | Fuel is represented by a dimensionless **spread multiplier** in `[0, inf)` plus an integer class label. No fuel-load, moisture, or fuel-model physics is represented. | STRUCTURAL |
| A-04 | `fuel_multiplier == 0` means strictly non-burnable (water, rock, wide road). | STRUCTURAL |
| A-05 | Terrain is synthetic (plane, ridge, or value-noise), not derived from any DEM. | SYNTHETIC |
| A-06 | Real Korean fuel-type distributions and their spread multipliers | UNKNOWN |

## B. Weather

| ID | Assumption | Class |
|---|---|---|
| B-01 | Wind is **spatially uniform** across the domain at any instant. Terrain channelling, slope/valley winds and gust structure are not modelled. | STRUCTURAL |
| B-02 | Wind speed and direction follow a mean-reverting AR(1) process about a scenario-specified schedule. | SYNTHETIC |
| B-03 | Temperature and relative humidity are generated but do **not** feed back into the fire model in v1. They exist so the weather observation stream is non-degenerate. | STRUCTURAL |
| B-04 | Real wind statistics (autocorrelation time, gust factor) for Korean wildfire episodes | UNKNOWN |

## C. Nature (fire) model

| ID | Assumption | Class |
|---|---|---|
| C-01 | Fire is represented purely as a **front arrival time field**. There is no fireline intensity, no crown fire, no fuel consumption, no burn-out physics. | STRUCTURAL |
| C-02 | Spread is elliptical about a combined wind+slope head direction (`docs/NATURE_MODEL.md`). The coefficients of the wind factor, slope factor and length-to-breadth relation are **synthetic**; they have the functional *form* commonly used in the literature but their numeric values are chosen for controllability, not calibrated. | SYNTHETIC |
| C-03 | Base rate of spread `R0` (default 3 m/min) is synthetic. | SYNTHETIC |
| C-04 | A cell, once ignited, can always act as a spread source (no extinction). Residence time affects **observability only**, not propagation. | STRUCTURAL |
| C-05 | Spotting is a stochastic downwind ignition process with a lognormal distance distribution. Firebrand physics is not modelled. | SYNTHETIC |
| C-06 | No suppression, no firebreak construction, no human intervention of any kind. | STRUCTURAL |
| C-07 | Calibrated rate-of-spread values for Korean fuels and terrain | UNKNOWN |

## D. Observation process

| ID | Assumption | Class |
|---|---|---|
| D-01 | All sensors are **generic**. No sensor in this repository is named after, or parameterised from, a real instrument. | STRUCTURAL (policy) |
| D-02 | A fire sensor observes an instantaneous snapshot of the actively-burning set at its scan time; integration over the scan is not modelled. | STRUCTURAL |
| D-03 | Detection probability for a sensor pixel is a saturating function of the actively-burning area within that pixel. Its coefficients are synthetic. | SYNTHETIC |
| D-04 | Geolocation error is isotropic Gaussian on the reported pixel centre, independent between pixels and scans. | SYNTHETIC |
| D-05 | False positives are a homogeneous Poisson process over the domain, independent of the fire. | SYNTHETIC |
| D-06 | Latency has a fixed component plus non-negative jitter; no latency is ever negative, so availability never precedes the event. | STRUCTURAL |
| D-07 | Weather-station error is additive Gaussian on speed and on the direction angle, independent between stations and times. | SYNTHETIC |
| D-08 | Real detection probabilities, revisit cadences and product latencies for any operational sensor | UNKNOWN |

## E. Randomness and reproducibility

| ID | Assumption | Class |
|---|---|---|
| E-01 | All randomness derives from a single `master_seed` through named, independent streams (`docs/DECISIONS.md#d-004`). | STRUCTURAL |
| E-02 | Determinism is claimed for a fixed `(config, seed, numpy version, platform floating-point)` tuple. Cross-platform bit-identity of floating-point rasters is **not** claimed; the determinism tests run within one environment. | STRUCTURAL |

## F. Time

| ID | Assumption | Class |
|---|---|---|
| F-01 | Internal time is **minutes since scenario `t0`**, a float. Wall-clock timestamps are derived from a configurable `epoch` and are presentational only. | STRUCTURAL |
| F-02 | There is no timezone modelling and no daylight-saving handling; `epoch` is UTC. | STRUCTURAL |
| F-03 | Diurnal cycles are not modelled in v1. | STRUCTURAL |
