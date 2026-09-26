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

The satellite's resources, instruments and value model are illustrative. The power system sheds processing and radio
loads so that the platform always survives the next eclipse.

**Scenarios.** Stress levels follow one rule, set on tuning days only (`tools/calibrate_scenarios.py`): each stress
scenario offers **2/3 of what "process everything" needs** of its resource.

| Scenario | Stress level |
|---|---|
| Nominal | no stress |
| Energy-starved | 44.8 W solar array |
| Storage-tight | 2.85 GB of mass memory |
| Compute-starved | an accelerator 4.72× slower |
| Downlink-starved | passes above 20° only, at half rate |
| Event surge | 5× more urgent events |

## Results (value captured, % of ideal; 20 real days per cell, mean ± 95% CI)

| Scenario | Value-aware (ours) | Bandwidth rules | Priority rules | Process-all | Bent-pipe |
|---|---|---|---|---|---|
| Nominal | **43.6 ± 1.2** | 41.9 ± 1.2 | 41.1 ± 1.2 | 40.7 ± 1.2 | 5.2 ± 0.3 |
| Energy-starved | **42.5 ± 1.2** | 38.3 ± 1.7 | 37.6 ± 1.8 | 22.2 ± 2.3 | 5.2 ± 0.3 |
| Downlink-starved | **33.2 ± 1.6** | 27.4 ± 2.6 | 27.6 ± 2.7 | 25.3 ± 2.6 | 1.1 ± 0.1 |
| Storage-tight | 36.9 ± 1.1 | 31.5 ± 1.2 | 37.1 ± 1.2 | **38.4 ± 1.1** | 10.6 ± 0.6 |
| Compute-starved | **38.7 ± 1.3** | 35.1 ± 1.5 | 36.1 ± 1.7 | 27.7 ± 1.3 | 5.2 ± 0.3 |
| Event surge | **31.1 ± 1.3** | 30.5 ± 1.3 | 30.2 ± 1.3 | 29.3 ± 1.2 | 2.0 ± 0.1 |

*The ideal value assumes instant delivery and unlimited resources. It is unreachable by design: most urgent events
occur hours away from any ground pass.*

- **Best decision quality in 5 of 6 scenarios.** The engine captures 2–20 % more value than the best baseline in
  each. Compared day by day, it beats every processing baseline on 18–20 of the 20 days in each of those scenarios.
- **Where it does not win.** When mass memory is the bottleneck, processing everything immediately is best
  (38.4 % vs 36.9 %). There the engine ties the rule set and beats the bandwidth-aware rules.
- **Less energy.** It spends 2–22 % less discretionary energy than the rule set and process-all (−22 % in the nominal
  case).
- **Protects the battery.** When energy-starved, process-all hits the load-shedding floor (10 %) and spends 55 % of
  the day below the reserve. The engine keeps a mean lowest charge of 28 %, and no strategy ever causes a power
  failure.
- **Trade-off.** Its *completion rate* (delivered + filtered onboard) is higher than the rules' when energy or
  storage is short, but 2–9 points lower otherwise. It drops items that can no longer reach the ground before their
  deadline, and it sends raw data when bandwidth allows instead of filtering it.
- **Robust.** The same ranking holds with a synthetic geometry (`results/synthetic/`).

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
python -m satsched.cli bench --seeds 20 --out results       # 6 scenarios x 5 strategies x 20 seeds (~2 min on 16 cores)
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

- **Scenarios:** nominal, energy-starved, downlink-starved (20° mask, half rate), storage-tight, compute-starved and
  event surge, on the real geometry (`src/satsched/scenarios.py`). Stress levels come from
  `tools/calibrate_scenarios.py`. The same six also exist with a synthetic geometry (`*_synthetic`).
- **Baselines:** bent-pipe, process-all, priority rules, and bandwidth-aware rules (`src/satsched/policies/baselines.py`).
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
