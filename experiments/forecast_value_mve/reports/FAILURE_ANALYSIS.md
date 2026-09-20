# FAILURE_ANALYSIS — why policies fail

Source: Stage B records, Figure 4.

## 1. The dominant failure mode is not the obvious one

Over all self-evacuation decisions in Stage B:

| outcome | count | share |
|---|---|---|
| mission completed | 4 269 | 84% |
| **route already blocked at departure** | **721** | **14%** |
| route cut en route | 109 | 2% |
| never ordered while threatened | 1 | <0.1% |

The expected failure — the fire cutting the road *while the convoy is on it* —
is rare. The common one is ordering **after the route has already closed**:
the decision was late, not the drive.

This matters for interpretation. The quantity a forecast has to get right is
not "will the fire cross the road", it is "**when will the road close, relative
to now**". A forecast that places the fire correctly but is 30 minutes stale
answers the first question and not the second — which is exactly why latency
flattens the benefit so sharply in `MVE_RESULTS.md` §2.

An earlier version of Figure 4 hid this: `route_already_burned` was missing
from the category list and 10–67% of every bar fell into an unlabelled "other"
bucket. The dominant failure mode was invisible until the categories were made
exhaustive.

## 2. Failure composition by policy (self-evacuation)

| policy | completed | already blocked | cut en route |
|---|---|---|---|
| tuned baseline | 88% | 10% | 1% |
| fixed buffer | 93% | 5% | 1% |
| fire-blind | 68% | 28% | 3% |
| forecast-aware, perfect, prompt | **98%** | 1% | 1% |
| forecast-aware, severe error, prompt | 77% | 18% | 5% |
| aggressive probe, severe error, prompt | 28% | 67% | 5% |

* **Fire-blind** fails by ignoring evidence: it orders at a fixed clock time
  regardless of where the fire is, and is late in 28% of worlds.
* **The tuned baseline** fails when its buffer trips after the route has
  closed — a buffer is a proxy for "is the fire near", not for "is the road
  still usable".
* **The aggressive probe under severe error** fails catastrophically (67%) in
  exactly one way: it waits for a predicted boundary that is in the wrong
  place, and the real boundary has already passed.
* **Route cut en route** never exceeds 5% for any policy. The full-traversal
  semantics matter, but they are not what separates the policies.

## 3. Why the conservative policy is robust

The frozen policy uses a 90-minute safety margin — it orders as soon as
anything within the forecast window would block the mission. Under displacement
error the *predicted* blocking geometry moves, but in most worlds *something*
still blocks within the window, so the policy still acts early. Its errors
degrade gracefully into "acted somewhat too early" (a lead-time charge) rather
than "acted after the road closed" (a failure).

The aggressive policy has no such cushion: it extracts the last feasible
minute, which is the point at which any forecast error converts directly into a
failure.

## 4. Failure modes of the *experiment*, not the policies

* **97% of worlds are threatened**, by construction of the ignition rule. The
  `unnecessary_action` term fires in 2 of 60 worlds, so the false-alarm side of
  the trade-off is barely exercised. A policy that over-evacuates is hardly
  punished here.
* **Mode B produced no forecast at all at the earliest epochs** in some worlds
  (median 17 of 17 epochs covered, but not all). Those decisions fall back to
  the buffer trigger, which pulls Mode B's behaviour toward the baseline and
  shrinks the measured contrast.
* **8 of 60 worlds reached the domain boundary** and 5 carried a discretisation
  warning. They were kept, because dropping worlds on an outcome-correlated
  criterion after the fact is exactly the selection the protocol forbids. Their
  effect on `ΔJ` has not been isolated.
* **The tuned baseline underperformed a fixed buffer on the held-out split**,
  so the primary comparison is mildly favourable to the forecast-aware policy.
