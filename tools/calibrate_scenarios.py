"""Calibrate the stress scenarios with one policy-independent rule, on the tuning seeds only.

Rule: in each stress scenario, the resource it is named after offers 2/3 of what the process-all
reference strategy needs in the nominal scenario (so the resource binds for every strategy that
processes data, whatever the engine under test does):
  - energy-starved:  daily discretionary energy (solar harvest - platform load) = 2/3 of process-all's use
  - storage-tight:   mass memory = 2/3 of process-all's peak storage
  - compute-starved: GPU time = 2/3 of process-all's GPU demand (a slower, lower-power accelerator,
                     same energy per job)

    python tools/calibrate_scenarios.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from satsched.metrics import compute_metrics  # noqa: E402
from satsched.policies import make_policy  # noqa: E402
from satsched.scenarios import get_scenario  # noqa: E402
from satsched.simulator.engine import run_simulation  # noqa: E402

TUNING_SEEDS = range(1000, 1004)
SUPPLY_FRACTION = 2.0 / 3.0


def main() -> int:
    nominal = get_scenario("nominal")
    sat, orbit = nominal.satellite, nominal.orbit
    runs = [run_simulation(nominal, make_policy("process_all"), seed) for seed in TUNING_SEEDS]
    metrics = [compute_metrics(r) for r in runs]
    energy = float(np.mean([m["energy_total_wh"] for m in metrics]))
    peak_mb = float(np.mean([r.series["storage_mb"].max() for r in runs]))
    gpu_frac = float(np.mean([m["gpu_util_pct"] for m in metrics])) / 100.0

    sunlit_h = 24.0 * (1.0 - orbit.eclipse_s / orbit.period_s)
    solar_w = (sat.base_load_w * 24.0 + SUPPLY_FRACTION * energy) / sunlit_h
    storage_mb = SUPPLY_FRACTION * peak_mb
    # slower accelerator: process-all's GPU demand becomes slowdown * gpu_frac of the time = 1 / SUPPLY_FRACTION
    slowdown = (1.0 / SUPPLY_FRACTION) / gpu_frac

    print(f"process-all reference (nominal, seeds {TUNING_SEEDS.start}-{TUNING_SEEDS.stop - 1}):")
    print(f"  discretionary energy {energy:.1f} Wh/day, peak storage {peak_mb:.0f} MB, GPU busy {100 * gpu_frac:.1f} %")
    print(f"  sunlit {sunlit_h:.2f} h/day, platform load {sat.base_load_w * 24:.0f} Wh/day")
    print("calibrated stress parameters:")
    print(f"  energy_starved : solar_w = {solar_w:.1f} W  (daily surplus {SUPPLY_FRACTION * energy:.0f} Wh)")
    print(f"  storage_tight  : storage_mb = {storage_mb:.0f} MB")
    print(f"  compute_starved: GPU slowdown = x{slowdown:.2f} (process-all would need the GPU {100 * slowdown * gpu_frac:.0f} % of the time)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
