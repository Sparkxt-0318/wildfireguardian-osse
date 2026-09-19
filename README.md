# wildfireguardian-osse

An **Observing System Simulation Experiment (OSSE) laboratory** for the
WildfireGuardian research programme.

It generates synthetic wildfire worlds whose hidden truth is completely known,
together with imperfect observation streams whose uncertainty, latency, cadence,
missingness and failure modes are explicitly controlled.

```text
HIDDEN NATURE WORLD          truth/         never given to a planner
        |
        v
OBSERVATION PROCESS          the only channel from truth to planner
        |
        v
AVAILABLE OBSERVATIONS       observations/  degraded, delayed, incomplete
```

> **Synthetic nature model for controlled experiments; not an operational
> wildfire forecast model.** Every coefficient is chosen for controllability,
> not calibrated against any fire. Results are statements about the synthetic
> system defined in `docs/NATURE_MODEL.md`, not about real wildfires
> (`docs/SCOPE.md`).

## Why

Real Korean wildfire datasets do not provide minute-scale *counterfactual* truth
for fire progression, road exposure, evacuation or assisted rescue: what was
observed is the result of the decisions that were actually taken. Evaluating a
decision system needs a world where the counterfactual is available. This
repository builds that world — and, just as importantly, builds the imperfect
view of it that a decision system would really have.

## The research question

> Can we generate reproducible wildfire-like synthetic worlds together with
> observation streams whose uncertainty, latency, cadence, missingness and
> failure modes are explicitly controlled?

The claim is not that the worlds are realistic. It is that **every departure of
the observations from the truth is a consequence of a parameter someone wrote
down**. `docs/RESEARCH_QUESTION.md` breaks that into eight testable
sub-questions, each with the test that answers it.

## Install

```bash
pip install -e .          # runtime: numpy, PyYAML
pip install -e ".[dev]"   # plus pytest
```

## Use

```bash
wg-osse selftest                              # generate + validate the 8 validation worlds
wg-osse generate config.yaml -o worlds/out    # a scenario, or a parameter sweep
wg-osse validate worlds/out                   # structure, checksums, leakage, timing
wg-osse summarize worlds/out --json s.json    # batch statistics
wg-osse scenarios                             # list the built-in validation worlds
wg-osse export-scenarios                      # write them to experiments/manifests/validation/
```

Reference batch (384 worlds):

```bash
wg-osse generate experiments/manifests/sweeps/reference_batch.yaml -o worlds/reference
wg-osse validate worlds/reference
wg-osse summarize worlds/reference --markdown worlds/reference/summary.md
```

Reading a world from Python — note that `available_at` is the **only** correct
way to consume observations:

```python
from wildfireguardian_osse.storage import load_world, available_at

world = load_world("worlds/reference/world_000001")
usable = available_at(world.fire_detections, t_min=45.0)   # legal at t = 45 min
```

Filtering on `event_time_min` instead would use observations before they were
delivered, and is the single most common way to manufacture optimistic results
(`docs/TIME_SEMANTICS.md#2`, `docs/FAILURE_MODES.md#L-03`).

## What a world looks like

```text
world_000001/
    truth/           hidden: arrival times, true weather, ignitions, every
                     hidden parameter, every seed, the false-positive ledger
    observations/    planner-visible: detections, scan log, station readings,
                     published sensor specs, static terrain/fuel-class context
    metadata/        planner-visible: identifiers, geometry, time window
    manifest.json    inventory: paths, sizes, sha256, visibility labels
```

Inside a world a planner may read `observations/` and `metadata/`, and nothing
else. Files are `.npy`, `.csv` and `.json` only, so a consumer needs nothing
from this package to read them.

## How truth stays hidden

Three independent mechanisms, because one is not enough:

1. **Layout and labels** — every file carries a `hidden` or `planner_visible`
   label in `manifest.json`, checked mechanically.
2. **A leakage scanner** — four attacks on every world: forbidden field names,
   forbidden values (seeds, truth rasters), swept values reaching planner-visible
   identifiers, and real-instrument names. `wg-osse validate` runs them.
3. **Prefix causality** — simulate a world to `H` and to `10H`; every
   observation available by `H` is bit-identical. No observation can depend on
   the future (`tests/test_causality_prefix.py`).

Plus: independent named random streams, so changing the sensor configuration
provably cannot change the fire (`docs/DECISIONS.md#d-004`).

## Documentation

Read in this order (`AGENTS.md` has the full working rules):

| Document | What it settles |
|---|---|
| `docs/PROJECT_CONTEXT.md` | what this is and what it is for |
| `docs/SCOPE.md` | what must **not** be built here |
| `docs/RESEARCH_QUESTION.md` | the question and its eight sub-questions |
| `docs/ASSUMPTIONS.md` | every assumption, classed SYNTHETIC / STRUCTURAL / **UNKNOWN** |
| `docs/DECISIONS.md` | append-only decision log with the rejected alternatives |
| `docs/NATURE_MODEL.md` | the fire model, in full, with its numerical limits |
| `docs/OBSERVATION_MODEL.md` | the observation operators and the hidden-variable boundary |
| `docs/TIME_SEMANTICS.md` | the four observation times and the usage rule |
| `docs/VALIDATION.md` | the eight validation worlds and the measured accuracy envelope |
| `docs/FAILURE_MODES.md` | simulated failure modes, **and how this lab can mislead you** |
| `docs/GLOSSARY.md` | vocabulary |

## Known limitations

Carried deliberately, not hidden (`docs/VALIDATION.md#5`, `tasks/ROADMAP.md`):

* **Wind is spatially uniform.** Stations differ only by noise, so spatial data
  assimilation cannot be studied with these worlds. This is the largest
  unrealism.
* **The spread coefficients are uncalibrated.** Real Korean rate-of-spread
  values are recorded as `UNKNOWN` (`docs/ASSUMPTIONS.md#C-07`).
* **No real sensor is modelled.** Real detection probabilities, cadences and
  latencies are `UNKNOWN` (`docs/ASSUMPTIONS.md#D-08`). Generic sensors are used
  on purpose, and a validator rejects real-instrument names.
* **The propagation stencil has a validity envelope.** Burned area is within
  ~15% of analytic for wind up to ~6 m/s at 30 m cells; beyond that it is
  under-predicted, and worlds record a warning when they leave the envelope.
* No fireline intensity, no suppression, no diurnal cycle, no moisture dynamics.

## Testing

```bash
pytest -q          # 158 tests
wg-osse selftest   # the eight validation worlds, generated and validated
```

## Status

Phase 1 complete. **Not integrated with any other WildfireGuardian repository**,
by explicit decision (`docs/DECISIONS.md#d-001`); the dependency direction is
one-way, outward.
