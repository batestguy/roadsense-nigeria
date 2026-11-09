# knowledge.md — RoadSense Nigeria, short version

## What it is

A measurement of change on Nigeria's 850 named federal road corridors, from 22 months of free
satellite imagery (September 2024 – June 2026), tested against the open procurement record of where
maintenance money went.

**The result is negative and that is the finding.** The pre-registered test failed: AUC 0.3901 against
a bar of 0.60, with the whole interval below 0.50 — corridors that received money score as *less*
degraded than comparable corridors that did not, which tracks road type rather than maintenance.

There is no model, no degradation index and no allocation tool. Do not assume one exists.

## Current state (2026-11-09)

- Measured: 69,212 readings, 850 corridors, 22 months, every month complete.
- Weather: monthly and daily features, 18,700 corridor-months, no gaps.
- Condition measure: 18,700 corridor-months, corridor and month effects removed.
- Validation: run twice, pre-specified, both failed. See `docs/findings.md` F23.
- Published: report page on GitHub Pages; dataset on Hugging Face, anonymous download verified.
- Written: article in `docs/article.md`. Preprint not started.

## The three URLs

- Report: <https://batestguy.github.io/roadsense-nigeria/publish/>
- Data: <https://huggingface.co/datasets/JBZABC/roadsense-nigeria>
- Source: <https://github.com/batestguy/roadsense-nigeria>

## Read these, in this order

| File | Why |
|---|---|
| `docs/handoff.md` | Current state, decisions, traps, what to do next |
| `docs/findings.md` | Every measured fact with its date; the source of truth |
| `docs/phases.md` | What is built, what failed, what follows |
| `docs/article.md` | The argument, in prose, for a reader who will not clone the repo |
| `preflight-spec.md` | Agreed scope and thresholds, committed before the tests ran |

## Two warnings for anyone continuing this work

1. **A value that is centred on a corridor's own mean, then averaged over that corridor, is exactly
   zero.** The first validation score did this and produced 726 corridors with one identical value.
   It looked like a result. A gate now blocks that failure mode.
2. **A check that cannot fail is not a check.** Two guards in this project were written so that no
   input could break them. Both were found late. When writing a guard, name the input that breaks it
   and run it.

## Not usable as

- A pavement rating. It observes reflectance, not roughness or structural condition.
- A causal claim about maintenance. 66 labelled corridors, observational comparison, no control trial.
- A commercial product. The weather reanalysis is free for non-commercial use only.
