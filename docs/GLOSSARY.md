# GLOSSARY

**Active / flaming set `A(t)`** — cells whose arrival time lies in
`(t − τ_res, t]`. The only part of the fire a fire sensor can observe.

**Acquisition time** — when the sensor finished recording an observation. See
`docs/TIME_SEMANTICS.md`.

**Anisotropy** — direction dependence of the spread rate. Here produced by the
elliptical rate-of-spread model about a wind+slope head direction.

**Arrival time field `T`** — the minute at which fire first reaches each cell;
`+inf` if never. The complete description of the fire in this model.

**Availability time** — the earliest instant an observation may legally be used.
The central concept of this repository.

**Backing rate** — spread rate directly opposite the head direction.

**Burned set `B(t)`** — cells with `T <= t`.

**Cadence** — the interval between successive sensor scans.

**Eccentricity `e`** — ellipse eccentricity derived from the length-to-breadth
ratio; `e = 0` is isotropic spread.

**Event time** — the physical instant of the world state an observation is
about.

**False negative** — a burning pixel a sensor failed to report.

**False positive** — a reported detection with no underlying fire. Unlabelled in
planner-facing files by design.

**Fire-correlated failure** — a missingness mode in which sensor failure hazard
rises as the fire approaches. Informative missingness; see
`docs/FAILURE_MODES.md#F-05`.

**Fuel multiplier `F`** — dimensionless per-cell scaling of the base spread
rate. `0` means non-burnable. A **hidden** model parameter.

**Fuel class `K`** — a coarse integer label for fuel type. Planner-visible as
static context; deliberately coarser than `F`.

**Head direction `θ_head`** — the direction of fastest spread, the vector sum of
the wind and slope enhancement vectors.

**Hidden truth** — everything under `truth/`. Never available to a planner.

**Informative missingness** — absence of data that is statistically dependent on
the hidden state. Not leakage, but an exploitable channel.

**Leakage** — any path by which hidden truth, hidden parameters or future
information reaches a planner-facing artifact. The thing this repository works
hardest to prevent.

**Length-to-breadth ratio `LB`** — ratio of the spread ellipse's long axis to
its short axis; `1` under no wind and no slope.

**Master seed** — the single integer from which every random stream is derived
by hashing. See `docs/DECISIONS.md#d-004`.

**MCAR** — missing completely at random; drop probability independent of
everything.

**Nature model** — the hidden world simulator. Synthetic; not an operational
forecast model.

**Observation process** — the operators mapping hidden truth to degraded,
delayed, incomplete planner-facing records.

**OSSE** — Observing System Simulation Experiment: an experiment in which a
known synthetic truth is observed through a simulated observing system, so that
the effect of the observing system on downstream decisions can be measured.

**Planner-facing / planner-visible** — files a decision system is allowed to
read: everything in `observations/` and `metadata/`.

**Prefix causality** — the property that observations available by time `H` do
not change if the simulation is run further. The strongest no-future-leakage
guarantee here.

**Processing time** — when the derived product existed, after acquisition and
before delivery.

**Residence time `τ_res`** — how long a cell stays flaming after ignition.
Affects observability only, never propagation (`docs/DECISIONS.md#d-010`).

**Spotting** — ignition ahead of the main front by lofted firebrands. Stochastic
and optional here.

**Stream** — a named, independently seeded random generator (`nature_seed`,
`sensor_seed`, …).

**Sweep** — a structured set of parameter combinations generating many worlds.

**World** — one complete generated instance: hidden truth plus its observation
streams plus metadata and manifest.
