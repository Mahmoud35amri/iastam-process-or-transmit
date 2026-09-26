"""Sensitivity of the value-aware engine to its parameters, on the tuning seeds only (1000-1003).

    python tools/sensitivity.py            # writes results/sensitivity.csv and prints a ranking
"""

from __future__ import annotations

import itertools
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from satsched.experiments import write_csv  # noqa: E402
from satsched.metrics import compute_metrics  # noqa: E402
from satsched.policies.value_aware import ValueAwareConfig, ValueAwarePolicy  # noqa: E402
from satsched.scenarios import SCENARIOS, get_scenario  # noqa: E402
from satsched.simulator.engine import run_simulation  # noqa: E402

TUNING_SEEDS = range(1000, 1004)
GRID = {"horizon_windows": [2, 3, 5], "storage_guard_s": [300.0, 900.0], "urgency_weight": [0.0, 1.0]}


def job(args: tuple) -> dict:
    scenario, params, seed = args
    cfg = ValueAwareConfig(**params)
    m = compute_metrics(run_simulation(get_scenario(scenario), ValueAwarePolicy(cfg), seed))
    return {"scenario": scenario, **params, "seed": seed, "value_score_pct": m["value_score_pct"],
            "time_below_reserve_pct": m["time_below_reserve_pct"]}


def main() -> int:
    combos = [dict(zip(GRID, values)) for values in itertools.product(*GRID.values())]
    jobs = [(s, c, seed) for s in SCENARIOS for c in combos for seed in TUNING_SEEDS]
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(job, jobs))
    write_csv(rows, ROOT / "results" / "sensitivity.csv")
    agg: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        agg[tuple(r[k] for k in GRID)].append(r["value_score_pct"])
    ranking = sorted(((sum(v) / len(v), k) for k, v in agg.items()), reverse=True)
    for mean, key in ranking:
        print(dict(zip(GRID, key)), f"mean value {mean:.2f} %")
    print(f"spread across {len(ranking)} configurations: {ranking[0][0] - ranking[-1][0]:.2f} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
