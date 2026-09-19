# PROJECT_CONTEXT

> **Read this file first.** Every agent (human or automated) working in this
> repository must read `docs/PROJECT_CONTEXT.md`, `docs/SCOPE.md`,
> `docs/ASSUMPTIONS.md`, `docs/DECISIONS.md` and `AGENTS.md` before writing code.

## What this repository is

`wildfireguardian-osse` is a **standalone Observing System Simulation Experiment
(OSSE) laboratory** for the WildfireGuardian research programme.

It does exactly two things:

1. It generates **synthetic wildfire worlds** in which the hidden truth
   (fire arrival time at every cell, true weather at every minute, every spot
   ignition, every model parameter) is completely known.
2. It generates **imperfect observation streams** of those worlds whose
   uncertainty, cadence, latency, missingness and failure modes are explicitly
   configured and explicitly recorded.

It does **not** do anything else. See `docs/SCOPE.md`.

## Why it exists

Real Korean wildfire datasets do not provide minute-scale counterfactual truth
for fire progression, road exposure, evacuation outcomes or assisted-rescue
outcomes. Observed outcomes are the result of decisions that were actually
taken; the counterfactual ("what if the decision had been different?") is never
observed. Any evaluation of a decision system therefore needs a controlled world
where the counterfactual *is* available.

An OSSE supplies that world. The price is that the world is synthetic, so any
conclusion drawn from it is a statement about the **synthetic system**, not about
Korean wildfires. `docs/SCOPE.md` and `docs/VALIDATION.md` state the resulting
limits on interpretation.

## The fundamental architecture

```text
HIDDEN NATURE WORLD          truth/        never given to a planner
        |
        v
OBSERVATION PROCESS          the only channel from truth to planner
        |
        v
AVAILABLE OBSERVATIONS       observations/ planner-facing, degraded, delayed
```

The observation layer must never expose hidden truth directly. The separation is
enforced three ways:

* **By storage layout** — hidden truth and planner-facing observations live in
  different directories with different visibility labels in `manifest.json`
  (`docs/OBSERVATION_MODEL.md`, `storage/manifest.py`).
* **By static tests** — a forbidden-field and forbidden-value scanner runs over
  every planner-facing artifact (`validation/leakage.py`, `tests/test_no_leakage.py`).
* **By a causality test** — observations available by time `H` are bit-identical
  whether the world is simulated to `H` or to `10H`, so no observation can depend
  on the future (`tests/test_causality_prefix.py`).

## Core research question

See `docs/RESEARCH_QUESTION.md`. In one line: *can we generate reproducible
wildfire-like synthetic worlds together with observation streams whose
uncertainty, latency, cadence, missingness and failure modes are explicitly
controlled?*

## Status

Phase 1 (nature model + observation process + validation + first batch) is
implemented. Integration with any other WildfireGuardian repository is
**out of scope** and has not been attempted. See `tasks/ROADMAP.md`.

## Vocabulary

Unfamiliar term? `docs/GLOSSARY.md`.

## `UNKNOWN` policy

Any quantity whose real-world value has not been verified from a primary source
is either (a) a freely chosen **synthetic** parameter, clearly labelled as such,
or (b) recorded as `UNKNOWN` in `docs/ASSUMPTIONS.md`. It is never silently
guessed. In particular this repository contains **no sensor named after a real
instrument**. See `docs/DECISIONS.md#d-002`.
