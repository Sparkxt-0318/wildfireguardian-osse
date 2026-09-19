# NATURE_MODEL

> **Synthetic nature model for controlled experiments; not an operational
> wildfire forecast model.**
>
> Every coefficient below is a *synthetic* parameter chosen for controllability
> and transparency. The functional forms are of a family commonly used in the
> wildfire-simulation literature (elliptical front propagation), but no
> coefficient here has been calibrated against any fire, in Korea or elsewhere.
> Do not quote a number produced by this model as a prediction.

## 1. State

The hidden world state at simulation time `t` (minutes since `t0`) is

| Symbol | Shape | Meaning |
|---|---|---|
| `Z` | `(ny, nx)` | elevation, metres (static) |
| `F` | `(ny, nx)` | fuel spread multiplier, dimensionless, `>= 0` (static) |
| `K` | `(ny, nx)` | integer fuel class label (static) |
| `T` | `(ny, nx)` | **fire arrival time**, minutes, `+inf` if never burned |
| `w(t)` | scalar pair | wind speed `U(t)` (m/s) and wind-to direction `θ_w(t)` (rad) |
| `S` | list | spot-ignition events `(t, cell, source_cell, distance)` |

`T` is the complete description of the fire. Derived quantities:

* burned set at `t`: `B(t) = { c : T[c] <= t }`
* actively burning (flaming, observable) set at `t`:
  `A(t) = { c : t - τ_res < T[c] <= t }` with `τ_res = residence_time_min`
* final perimeter: boundary of `B(t_end)`

Grid geometry: regular square raster, cell size `dx` metres, local Cartesian
coordinates with `x` east and `y` north, origin at the south-west corner of
cell `(0, 0)`. Cell centre of `(i, j)` is `((j + 0.5) dx, (i + 0.5) dx)`.

## 2. Terrain derivatives

Slope and aspect use central differences (one-sided at the boundary):

```
gx = ∂Z/∂x ,  gy = ∂Z/∂y
slope     = arctan( sqrt(gx² + gy²) )
upslope θ_s = atan2(gy, gx)            # direction of steepest ascent
```

## 3. Rate of spread

### 3.1 Base rate

```
R0[c] = R0_base · spread_multiplier · F[c]          [m/min]
```

`R0_base` (default `3.0` m/min) and `spread_multiplier` (a sweep knob, default
`1.0`) are synthetic. Cells with `F[c] = 0` never burn.

### 3.2 Wind and slope factors

```
φ_w(t) = a_w · U(t)^b_w                    a_w = 0.40, b_w = 1.50   (synthetic)
φ_s[c] = a_s · tan(slope[c])²              a_s = 3.00               (synthetic)
```

`φ_w` and `φ_s` are dimensionless *enhancement* factors: `φ = 0` means no
enhancement over `R0`.

### 3.3 Combination

Wind and slope enhancements are combined as **vectors**, which is what makes the
head direction a compromise between "downwind" and "upslope":

```
v = φ_w(t) · (cos θ_w, sin θ_w) + φ_s[c] · (cos θ_s[c], sin θ_s[c])
φ[c,t]      = ‖v‖
θ_head[c,t] = atan2(v_y, v_x)
```

### 3.4 Elliptical directional rate

```
R_head = R0[c] · (1 + φ)
LB     = 1 + c_lb · φ^p_lb                 c_lb = 0.07, p_lb = 1.50 (synthetic)
e      = sqrt(LB² − 1) / LB
R(θ)   = R_head · (1 − e) / (1 − e·cos(θ − θ_head))
```

This is the standard focus-at-ignition ellipse. Consequences, all checked in
`tests/test_ros.py`:

* `φ = 0` ⟹ `LB = 1`, `e = 0`, `R(θ) = R0` for all `θ` — **isotropic**.
* `θ = θ_head` ⟹ `R = R_head` (heading rate).
* `θ = θ_head + π` ⟹ `R = R_head (1−e)/(1+e)` (backing rate).
* `R(θ)` is maximal at `θ_head` and minimal at `θ_head + π` for `e > 0`.
* `LB` is the ratio of the ellipse's long to short axis.

**Why `p_lb = 1.5` and not something smaller.** `e ≈ sqrt(2·c_lb·φ^p_lb)` for
small `φ`, so an exponent below 1 makes the eccentricity rise with an infinite
slope at zero wind: a first breath of wind would instantly collapse the flank
rate. With the original `c_lb = 0.50, p_lb = 0.80` the flank rate fell to 0.66·R0
at `U = 0.5 m/s` and the **total burned area decreased** with wind all the way to
`U ≈ 2.2 m/s` — the opposite of the behaviour the model is meant to exhibit, and
a trap for any sweep over low wind speeds. With `c_lb = 0.14, p_lb = 1.5` the
area is monotone in wind speed apart from a 1.7% dip at `U ≈ 0.16 m/s`, and
`LB` is 1.8 at 4 m/s, 3.0 at 6 m/s and 7.3 at 10 m/s. See
`docs/DECISIONS.md#d-015`.

## 4. Front propagation

Time is stepped with a fixed `dt` (default `1.0` min). The front is advanced on
the 8-connected raster by **fractional edge accumulation**, an explicit,
auditable discretisation of the Huygens principle:

For direction `k ∈ {8 neighbours}` with unit vector `u_k`, bearing `θ_k` and
edge length `d_k = dx·‖offset_k‖`:

```
for each step [t, t+dt]:
    # uncredited burning time of every potential source, in minutes
    a[c] = max(t+dt − T[c], 0)
    c[c] = a[c] − credited[c] ;  credited[c] = a[c]
    for each k:
        tgt = sources shifted by offset_k, restricted to T[tgt] = +inf and F[tgt] > 0
        r_k = ½ ( R_src(θ_k) + R_tgt(θ_k) )        # edge rate, both endpoints
        Φ[k, tgt] += r_k · c[src] / d_k            # fraction of the edge crossed
    ignite tgt where Φ[k, tgt] >= 1
```

The **credit ledger** `credited[·]` is not a detail. A cell whose arrival time
falls part-way through a step is only *discovered* at the end of that step, so a
naive scheme silently discards the remainder of the step — losing up to one `dt`
per cell crossed and making the whole fire run about 10% slow at `dt = 1 min`,
with the error depending on `dt`. Crediting each source with exactly
`t + dt − T[c]` minutes of spreading, no more and no less, removes both the bias
and the `dt` dependence: on a uniform no-wind landscape the arrival times are
now exact (`10.0, 20.0, 30.0, …` minutes per 30 m cell at `R0 = 3 m/min`) and
**identical for `dt = 1.0` and `dt = 0.5`**.

Sub-step interpolation gives a smooth arrival time: if `Φ` crossed 1 during the
step with increment `δ`, then

```
T[tgt] = t + dt · (1 − Φ_before) / δ
```

and when several directions ignite the same cell in one step, the minimum is
taken. Averaging the rate over both endpoints (`r_k`) is what makes a fire slow
down as it enters poorer fuel; the hard gate `F[tgt] > 0` is what makes a
non-burnable cell an absolute barrier.

**Numerical note.** The scheme is explicit and first-order. It is stable for any
`dt` (fractions simply saturate). Its accuracy limit is the sub-step arrival
interpolation, which degrades once the front crosses more than one cell per
step. Measured against a 4× finer step on a uniform landscape: at Courant
`max(R)·dt/dx = 0.55` the arrival-time fields agree to a mean of 0.10 min
(IoU 0.998), while at 1.36 they differ by a mean of 8.7 min (IoU 0.943). A
configuration exceeding `1.0` therefore records a warning in the world manifest
(`docs/FAILURE_MODES.md#G-05`).

The remaining error is **angular, not temporal**. A stencil can only travel along
its own directions, so an intermediate bearing must be approximated by a
staircase, and the resulting path is longer than the straight line. With 8
directions the worst case is `cos θ + (√2−1) sin θ ≈ 1.082` at `θ = 22.5°`. The
stencil is therefore configurable — `nature.stencil_max_offset` of 1, 2 or 3
gives 8, 16 or 32 directions — and the **default is 16**
(`docs/DECISIONS.md#d-016`).

The error is far worse for an *elliptical* front than for a circular one,
because the staircase mixes moves whose rates differ by more than an order of
magnitude. `docs/VALIDATION.md#4` has the measured table and the resulting
validity envelope; the short version is that 8 directions make the burned area
non-monotone in wind speed, which is why they are not the default.

Reducing `dt` does not help with any of this — the credit ledger already removed
the temporal error. Do not mistake the residual for physical anisotropy
(`docs/FAILURE_MODES.md#L-06`).

A multi-cell move is blocked unless every cell its segment touches is burnable,
so a one-cell-wide non-burnable line remains an absolute barrier under every
stencil.

## 5. Spotting (optional)

Disabled by default. When enabled, at every `spotting_interval_min`:

```
λ      = spot_rate_per_ha_per_min · area_ha(A(t)) · interval
N      ~ Poisson(λ)
for each of N firebrands:
    origin   ~ Uniform(A(t))
    distance ~ Lognormal(µ = log(median_distance_m), σ = sigma_log)
    bearing  ~ Normal(θ_w(t), σ_bearing)
    land     = origin + distance · (cos bearing, sin bearing)
    ignite land if in-domain, unburned, F > 0, and Bernoulli(p_ignite · min(1, F))
```

A successful spot sets `T[land] = t` and the cell becomes an ordinary source
thereafter. Every attempt (successful or not) is recorded in
`truth/ignitions.json`. Spot ignitions are **never** written to a planner-facing
file; the planner can only see them through the ordinary detection process.

All spotting randomness comes from the `spotting_seed` stream, which is not
consumed at all when spotting is disabled — so `spotting: off` is exactly
equivalent to a run of a model without spotting (`tests/test_spotting.py`).

## 6. Weather

Wind speed and direction follow a mean-reverting AR(1) process around a
scenario **schedule** (a piecewise-linear target in time, which is how a
"wind-direction shift" scenario is expressed):

```
U(t+Δ)   = Ū(t+Δ) + ρ_U   · (U(t)   − Ū(t))   + σ_U   · sqrt(1−ρ_U²)  · ε
θ_w(t+Δ) = θ̄(t+Δ) + ρ_θ · wrap(θ_w(t) − θ̄(t)) + σ_θ · sqrt(1−ρ_θ²) · ε'
ρ = exp(−Δ / τ)
```

`U` is clipped at 0. Temperature and relative humidity are generated by the same
machinery but **do not feed back into the fire model in v1**
(`docs/ASSUMPTIONS.md#B-03`). All weather randomness comes from `weather_seed`.

## 7. What the nature model does not contain

No fireline intensity, no crown fire, no fuel consumption or burn-out, no
suppression, no atmospheric feedback, no diurnal cycle, no spatial wind field,
no moisture dynamics. See `docs/ASSUMPTIONS.md#C` and `docs/SCOPE.md`.
