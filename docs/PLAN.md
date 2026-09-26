# Plan — Problem 1: "Process or Transmit?"

## Goal
Build a decision engine that, at every time step and for every onboard data item, chooses one of:
**PROCESS_NOW** (onboard), **STORE** (keep for later processing or transmission),
**TRANSMIT** (raw downlink), or **DROP** (only under storage pressure). The engine maximises the
delivered scientific/operational value under energy, CPU/GPU, RAM, storage, bandwidth,
contact-window and latency constraints.

## Deliverables (deadline 2026-09-26 23:59)
| Deliverable | Location |
|---|---|
| Code repository (simulator, engine, baselines, tests) | `src/satsched`, `tests/` |
| Simulation + experiment harness | `python -m satsched.cli` |
| Dataset (synthetic benchmark: workloads, passes, eclipses, results) | `data/`, `results/` |
| Dashboard + demo (replay of a simulated day, policy comparison) | `dashboard/index.html` |
| Interim research paper | `docs/paper/` |
| Poster draft | `docs/poster/` |
| Pitch video script | `docs/pitch/` |

## Architecture
```
src/satsched/
  config.py      scenario, satellite, orbit and data-type parameters (frozen dataclasses)
  scenarios.py   nominal + stress scenarios
  models.py      DataItem, Stage, Plan, Observation
  orbit.py       eclipse and ground-contact schedule, capacity forecasts
  workload.py    seeded instrument data generator (the dataset)
  valuation.py   value model: priority x usefulness x timeliness decay
  simulator/     physics (energy, storage, compute, downlink), engine loop
  policies/      baselines + value-aware shadow-price engine
  metrics.py     evaluation metrics
  experiments.py scenario x policy x seed grid (parallel)
  export.py      dataset + dashboard JSON export
  plots.py       figures
  cli.py         command line entry point
```

## Decision engine (shadow-price scheduler)
1. Expected value of each option (raw vs processed), from the predicted delivery time.
2. Prices for scarce resources, derived by greedy market clearing over the forecast horizon:
   the downlink price (value/MB) and the energy price (value/Wh, zero when a full battery would spill solar power).
3. Net utility = expected value − Σ price × consumption; take the argmax route.
4. Sub-schedulers: processing admission (gain per compute-second, energy guard), downlink
   ordering (value density + urgency regret), storage guard (free-space reserve).
5. Re-evaluated every step (receding horizon); each decision is explainable.

## Evaluation
- Baselines: bent-pipe (transmit all raw, FIFO), process-all (FIFO), static priority rules.
- Scenarios: nominal, energy-starved, downlink-starved, storage-tight, event-surge; 10+ seeds each.
- Metrics:
  - value captured (% of ideal)
  - completion rate
  - energy: Wh, Wh/value, min SOC, time below reserve
  - latency: mean and p95, per type
  - utilisation: CPU/GPU, downlink, storage

## Schedule
| Time | Work |
|---|---|
| 12:20–15:30 | core code + tests |
| 15:30–16:30 | experiments + dataset |
| 16:30–18:00 | dashboard/demo |
| 18:00–20:30 | paper |
| 20:30–21:30 | poster + pitch |
| 21:30–23:00 | review, README, packaging |

## Risks
- Synthetic parameters: document them, sweep scenarios, avoid overclaiming.
- Overfitting the engine to the simulator: tune on seeds 1000+, evaluate on seeds 0–N.
- Runtime: vectorised policy, parallel experiment runs.
