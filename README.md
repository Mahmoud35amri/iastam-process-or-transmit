# Process or Transmit? A value-aware onboard decision engine

**IASTAM · Problem 1.** A satellite produces data continuously, but its energy, CPU/GPU, memory, storage and
ground-contact time are limited. For every data item, and at every 30-second decision step, this engine decides
whether to **process it onboard now**, **store it** for later processing or transmission, **transmit it** to the ground,
or, as a last resort, **drop it**. It chooses whichever option maximises the scientific and operational value that
actually reaches the ground.

The engine prices each scarce resource: downlink MB, energy Wh, GPU-seconds, CPU-seconds and storage MB. Every item
then takes the option with the best **net value = expected value − Σ price × resource used**. The prices are recomputed
at every step from forecasts of ground passes, eclipses and battery state, using Lagrangian relaxation / dual
decomposition. The engine is cheap, has no training phase, and explains every decision in one line.

**Real orbit geometry.** The satellite flies the real orbit of **Sentinel-2A**: 786 km, sun-synchronous, 100.6-min
period, from its CelesTrak TLE of 26 Sep 2026. The orbit is propagated with SGP4 via
[skyfield](https://rhodesmill.org/skyfield/).

- **Passes:** computed over a ground station at **CNES Toulouse** above a 10° elevation mask, about 4.4 passes and
  21.5 GB of downlink per day.
- **Eclipses:** computed from the JPL DE421 ephemeris, about 34 min per orbit.
- **Seeds:** each seed simulates a different real day.

The satellite's resources, instruments and value model are illustrative.

## Results (20 real days per cell, mean ± 95% CI)

| Scenario | Value-aware (ours) | Priority rules | Process-all | Bent-pipe | Energy vs rules |
|---|---|---|---|---|---|
| Nominal | **43.6 ± 1.2 %** | 41.1 ± 1.2 % | 40.7 ± 1.2 % | 5.2 ± 0.3 % | −22 % |
| Energy-starved | **43.3 ± 1.2 %** | 41.0 ± 1.3 % | 27.2 ± 3.5 % | 5.2 ± 0.3 % | −13 % |
| Downlink-starved | **33.2 ± 1.6 %** | 27.6 ± 2.7 % | 25.3 ± 2.6 % | 1.1 ± 0.1 % | −2 % |
| Storage-tight | 41.0 ± 1.2 % | 41.1 ± 1.2 % | 40.7 ± 1.2 % | 11.1 ± 0.5 % | −34 % |
| Event surge | **31.1 ± 1.3 %** | 30.2 ± 1.3 % | 29.3 ± 1.2 % | 2.0 ± 0.1 % | −21 % |

*Value captured, as % of the ideal value (instant delivery, unlimited resources). The ideal is unreachable by design:
most urgent events occur hours away from any ground pass.*

- **Best decision quality in 4 of 5 scenarios.** Compared day by day, the engine beats both processing baselines on
  all 20 days in four scenarios. It captures 3–21 % more value than a hand-tuned rule set and 6–59 % more than
  "process everything". With only 8 GB of storage it ties the rule set (−0.1 ± 0.4 points), using 34 % less energy.
- **Less energy.** It spends 2–35 % less discretionary energy than the processing baselines (−22 % in the nominal case).
- **Protects the battery.** In the energy-starved case, process-all drops to a mean lowest charge of 4 % and spends
  43 % of the day below the reserve. The engine keeps a mean lowest charge of 35 % and is below the 30 % reserve only
  1.1 % of the time.
- **Trade-off.** It delivers the most items in every scenario, yet its *completion rate* (delivered + filtered
  onboard) is 2–9 points lower than the rule set's. It drops items that can no longer reach the ground before their
  deadline instead of letting them expire, and it sends raw data when bandwidth allows instead of filtering it. See
  the paper for the discussion.
- **Robust.** With a synthetic geometry (95-min orbit, 6 fixed passes/day) the engine ranks first in all 5
  scenarios; see `results/synthetic/`.

The full tables are in [`results/summary.md`](results/summary.md). The per-run metrics are in `results/runs.csv`, and
the ablation results in `results/ablation_*`.

## Deliverables

| Deliverable | Where |
|---|---|
| Code (simulator, engine, baselines, tests) | `src/satsched/`, `tests/` |
| Simulation + experiment harness | `python -m satsched.cli …` (below) |
| Dataset (items with hidden ground truth; real Sentinel-2A passes and eclipses) | [`data/`](data/README.md) |
| Dashboard / demo (benchmark explorer + replay of one day with the engine's explanations) | [`dashboard/index.html`](dashboard/index.html) |
| Interim research paper | [`docs/paper/`](docs/paper/) |
| Poster draft (A1) | [`docs/poster/poster.pdf`](docs/poster/poster.pdf) |
| Pitch video script | [`docs/pitch/pitch_script.md`](docs/pitch/pitch_script.md) |
| Figures | [`docs/figures/`](docs/figures/) |

## Quick start

Requirements: Python ≥ 3.11 with `numpy` and `matplotlib`, plus `pytest` and `pytest-cov` for the tests. `skyfield`
(and the 17 MB JPL `de421.bsp`, downloaded to `data/orbit/`) is needed only to recompute the orbit geometry: the
computed passes and eclipses are already in `data/orbit/sentinel2a_toulouse/`.

```bash
pip install -e ".[dev]"            # or: set PYTHONPATH=src

python -m pytest --cov             # tests with coverage

python -m satsched.cli geometry                            # (optional) recompute passes + eclipses from the TLE
python -m satsched.cli run --scenario energy_starved --policy value_aware --seed 0   # one simulated (real) day
python -m satsched.cli bench --seeds 20 --out results       # 5 scenarios x 4 strategies x 20 seeds (~1.5 min on 16 cores)
python -m satsched.cli ablation --seeds 20 --out results    # engine with components switched off
python -m satsched.cli dataset --seeds 3 --out data         # export the benchmark dataset
python -m satsched.cli figures --out docs/figures           # paper / poster figures
python tools/sensitivity.py                                # parameter sensitivity on the tuning seeds
python tools/build_paper.py                                # paper: HTML, PDF, DOCX
python -m satsched.cli demo --seed 7 --out dashboard/data.js   # dashboard data, then open dashboard/index.html
```

## How it works

```
instruments ──► onboard storage ──► decision engine (every 30 s) ──► CPU/GPU  (process now)
                                      │ 1 value options            ──► radio    (transmit during passes)
forecasts: passes, eclipses, ─────────► 2 price resources           ──► storage  (keep for later) / drop
battery, queues                       │ 3 best net option
                                      │ 4 admission · downlink order · storage guard
```

1. **Value each option.** An item's value is *priority × usefulness × timeliness*. Usefulness is uncertain: a scene
   may be cloudy, an event candidate a false alarm. Onboard processing reveals it, discards useless items and shrinks
   useful ones, but keeps only part of the value. Raw data keeps full value but is large and needs ground processing
   (delay).
2. **Price the resources.** Prices rise, by coordinate-wise bisection, until the planned use of each resource over the
   next ground passes fits its forecast supply. A price is zero when the resource is plentiful. For example, energy is
   free when the battery is full in sunlight.
3. **Choose.** Each item takes PROCESS, RAW or NONE by net utility. A second pass re-values raw transmissions at their
   position in the downlink queue.
4. **Execute safely.** Processing starts only if a slot, RAM and the battery reserve through the next eclipse and pass
   allow it; otherwise the item is stored. Downlink order is value per MB plus urgency. A storage guard keeps room for
   incoming data.

## Repository layout

```
src/satsched/
  config.py, scenarios.py    satellite, orbit and data-type parameters; 5 benchmark scenarios
  models.py                  immutable DataItem, Plan, Observation, Explanation
  orbit.py                   eclipses, ground-contact windows, capacity forecasts
  geometry.py                real orbit geometry: skyfield/SGP4 passes + eclipses, one real day per seed
  workload.py                seeded instrument data generator (hidden ground truth)
  valuation.py               value model
  simulator/                 physics (energy, storage, compute, downlink) + run loop
  policies/                  baselines.py, pricing.py (dual decomposition), value_aware.py
  metrics.py, experiments.py evaluation (5 criteria) and parallel benchmark harness
  export.py, plots.py, cli.py
tests/                       unit + integration tests (pytest, ~99 % coverage of the core)
```

## Evaluation protocol

- **Scenarios:** nominal, energy-starved, downlink-starved (20° mask, half rate), storage-tight, event surge, on the
  real geometry (`src/satsched/scenarios.py`). The same five also exist with a synthetic geometry (`*_synthetic`).
- **Seeds:** engine parameters were tuned on seeds 1000–1003 only (real days 24–27). All reported results use seeds
  0–19 (real days 26 Sep–15 Oct 2026). Every strategy sees the same passes and the same data for a given seed.
- **Metrics, grouped by the five criteria of the brief:**
  - *decision quality*: value captured
  - *task completion*: completion, delivery, loss and backlog rates
  - *energy*: Wh, Wh per unit of value, minimum battery, time below reserve
  - *latency*: mean, p95 and urgent-alert latency
  - *resource utilisation*: CPU, GPU, downlink and storage

## Limitations

Orbit, passes and eclipses are real. The satellite's resources, workload and value parameters are illustrative
orders of magnitude, not a specific mission. The value model (priority × usefulness × exponential timeliness decay) is
an assumption that operators would calibrate. The engine's pass and eclipse forecasts come from the same propagated
orbit, so they are exact. The engine is compared with heuristics, not yet with a hindsight
optimum; closing that gap is the next step (see the paper).
