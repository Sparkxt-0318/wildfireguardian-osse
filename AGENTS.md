# AGENTS

Operating rules for anyone — human or automated — working in this repository.

## 0. Read first, in this order

1. `docs/PROJECT_CONTEXT.md`
2. `docs/SCOPE.md` — what must **not** be built here
3. `docs/RESEARCH_QUESTION.md`
4. `docs/ASSUMPTIONS.md`
5. `docs/DECISIONS.md`
6. `docs/NATURE_MODEL.md` and `docs/OBSERVATION_MODEL.md`
7. `docs/TIME_SEMANTICS.md`
8. `docs/FAILURE_MODES.md`
9. `tasks/CURRENT.md`

Then and only then, write code.

## 1. Standing rules

* **The observation layer must never expose hidden truth.** If a change makes a
  new field planner-visible, it needs a `docs/DECISIONS.md` entry, an entry in
  the leakage allow-list with a written rationale, and a test.
* **Unknown quantities are labelled `UNKNOWN`.** Never invent a specification.
* **Never name a sensor after a real instrument.** `docs/DECISIONS.md#d-002`.
  A validator enforces this; do not weaken it.
* **Never break determinism.** New randomness goes through a *named stream*
  (`rng.py`), never through a bare `np.random` call or a shared generator.
  Generators are only ever built by `SeedRegistry.generator(stream, tag)`:
  `grep -rn "default_rng\|np\.random\.seed\|RandomState" src/` must match
  nothing outside `rng.py` (a `np.random.Generator` *type annotation* is fine).
  A quantity whose number of draws can vary needs its **own sub-stream**, or it
  will shift everything drawn after it — see the note in `rng.derive_seed`.
* **Never widen scope.** If a task seems to need routing, rescue, forecast value
  or real data, stop and write it in `tasks/CURRENT.md` under "Deferred".
* **Every new degradation is a named parameter**, documented in
  `docs/OBSERVATION_MODEL.md` and swept-able.
* **Append to `docs/DECISIONS.md`**, never edit an existing entry.
* `pytest` must pass before any commit.

## 2. The three roles

Work in this repository is organised into three roles. One person may play all
three, but the *outputs* of each must exist separately.

### Agent A — Model Auditor
Owns the specification, before implementation.

Defines and keeps current: the mathematical state; the propagation assumptions;
the observation semantics; the temporal semantics; the hidden-variable boundary.
**Looks specifically for leakage** — in the design, not just the code: any path
by which hidden truth, a hidden parameter, or future information could reach a
planner-facing artifact.

Outputs: `docs/NATURE_MODEL.md`, `docs/OBSERVATION_MODEL.md`,
`docs/TIME_SEMANTICS.md`, `docs/ASSUMPTIONS.md`, `docs/DECISIONS.md`,
and the hidden-variable boundary in `docs/OBSERVATION_MODEL.md#6`.

*Audit standard:* for every field in every planner-facing schema, state which
function computed it and from which truth quantities at which times. If that
sentence cannot be written, the field does not ship.

### Agent B — Implementation Engineer
Builds to the specification: simulator, observation generators, configuration,
storage, CLI, tests.

*Standard:* no behaviour that is not in the docs; no parameter that is not in a
config dataclass with a default; no randomness outside a named stream; every
public function typed and docstringed with its units.

### Agent C — Red-Team Validator
Attempts to break the laboratory. Specifically tries to:

* **recover truth from accidentally leaked fields** — reconstruct the arrival
  time field, the ignition point, or the final perimeter from `observations/`
  alone, better than the observation process should allow;
* **find seed contamination** — show that changing an observation-side seed
  perturbs the truth, or that two "independent" streams are correlated;
* **find future-data leakage** — show that an observation available at `t`
  depends on the world after `t` (prefix-causality attack);
* **break deterministic reproduction** — find an ordering, dict-iteration,
  float-accumulation or filesystem dependence that makes two runs differ;
* **test physical and qualitative edge cases** — zero wind, zero fuel, ignition
  on a non-burnable cell, ignition at the domain edge, `dt` far too large,
  extreme wind, `p_detect_max = 0`, `p_missing = 1`, horizon shorter than one
  cadence.

Outputs: tests under `tests/`, and a findings entry in `tasks/COMPLETED.md`.
A red-team finding that cannot be fixed immediately becomes a documented
limitation in `docs/FAILURE_MODES.md`, never a silent omission.

## 3. Workflow

1. Pick a task from `tasks/CURRENT.md` (or add one).
2. Agent A: confirm or extend the specification **first**. Docs precede code.
3. Agent B: implement, with tests.
4. Agent C: attack it; add adversarial tests.
5. Move the task to `tasks/COMPLETED.md` with a one-line outcome.
6. `pytest -q` green, `wg-osse selftest` green.

## 4. Conventions

* Python ≥ 3.10. Runtime deps: `numpy`, `PyYAML`. Tests: `pytest`.
* Units in every name or docstring: `_m`, `_min`, `_ms` (m/s), `_deg`, `_ha`.
* Internal time is **float minutes since `t0`**. Wall-clock is presentational.
* Angles are radians internally, **degrees in configs and CSV outputs**.
  Direction convention: `wind_dir_deg` is the direction the wind blows
  **toward**, measured counter-clockwise from east (mathematical convention),
  and this is stated wherever it appears. It is *not* meteorological
  "direction from".
* Outputs: `.npy`, `.csv`, `.json` only — a consumer must not need this package.
