# experiments

Scenario and sweep manifests, and where generated batches go.

```text
experiments/
    manifests/
        validation/     the eight validation worlds, as YAML
        sweeps/         parameter sweeps
```

## `manifests/validation/`

**Generated artifacts — do not hand-edit.** The source of truth is
`src/wildfireguardian_osse/scenarios/library.py`; these files are written by

```bash
wg-osse export-scenarios experiments/manifests/validation
```

They exist so the validation worlds are readable as data, and so a diff shows
when a scenario changed. Each file is the *fully defaulted* scenario, so it also
serves as a complete reference for every configuration key.

What each world checks is in `docs/VALIDATION.md#1`.

## `manifests/sweeps/`

`reference_batch.yaml` — the 384-world reference batch:

```bash
wg-osse generate experiments/manifests/sweeps/reference_batch.yaml -o worlds/reference
wg-osse validate worlds/reference
wg-osse summarize worlds/reference --markdown worlds/reference/summary.md
```

Axes: ignition point (3) × wind speed (4) × wind direction (4) × spread
multiplier (2) × spotting on/off (2) × detection latency (2).

## Writing a sweep

```yaml
base:            # an inline scenario, or use `base_scenario: v2_uniform_constant_wind`
  name: my_batch
  ...
sweep:
  mode: grid     # or `random` with `n_samples`
  max_worlds: 500
  master_seed: 20260919
  axes:
    - path: weather.wind_speed_ms
      values: [0.0, 3.0, 6.0]
```

Three rules, all enforced:

1. **No axis may target `name`, `description` or `tags`.** Those are
   planner-visible; swept values are hidden parameters
   (`docs/DECISIONS.md#d-013`). The loader rejects such an axis, and the leakage
   scanner independently checks the generated worlds.
2. **Stay inside the discretisation validity envelope** (`docs/VALIDATION.md#4`).
   Sweeping wind past ~6 m/s at 30 m cells under-predicts burned area and can
   make it non-monotone — an artefact that looks exactly like a finding.
3. **Size the domain and horizon so fires do not reach the boundary.** Worlds
   that do are flagged `boundary_contact` and must be excluded from area
   analyses (`docs/FAILURE_MODES.md#G-04`); `wg-osse summarize` counts them.

## Output layout

```text
worlds/<batch>/
    world_000000/ ... world_000383/    completed worlds
    batch_index.jsonl                  one line per completed world, with its summary
    failures.jsonl                     one line per failed world (absent if none)
    .world_XXXXXX.partial/             an interrupted write; never a valid world
```

Generated worlds are **not committed** (`.gitignore`): they are reproducible
from the manifest and the master seed. A batch directory is a build artifact,
not a source.

## `results/`

`reference_batch_summary.md` / `.json` — the summary of the 384-world reference
batch, kept as a result record so the repository carries evidence of what the
laboratory produced without committing ~2 GB of worlds. Regenerate the batch
from the manifest and `master_seed: 20260919` to reproduce it exactly.
