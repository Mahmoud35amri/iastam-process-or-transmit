"""Benchmark harness: every scenario x policy x seed, run in parallel, then aggregated.

Rows are plain dicts (no pandas dependency); tables are written as CSV and Markdown.
"""

from __future__ import annotations

import csv
import logging
import math
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from satsched.metrics import compute_metrics
from satsched.policies import make_policy
from satsched.policies.value_aware import ValueAwareConfig, ValueAwarePolicy
from satsched.scenarios import get_scenario
from satsched.simulator.engine import run_simulation

log = logging.getLogger(__name__)

Row = dict[str, float | str | int]

HEADLINE = [
    "value_score_pct", "completion_rate_pct", "energy_total_wh", "wh_per_value", "min_soc_pct",
    "time_below_reserve_pct", "latency_mean_min", "latency_p95_min", "alert_latency_mean_min",
    "alerts_delivered_pct", "gpu_util_pct", "cpu_util_pct", "downlink_util_pct", "storage_mean_pct",
    "storage_peak_pct", "overflow_pct", "dropped_pct", "expired_pct", "discarded_onboard_pct",
    "processed_onboard_pct", "sent_raw_pct", "backlog_pct", "spilled_solar_wh", "brownout_wh",
    "stalled_job_steps", "delivered_pct",
]
MARKDOWN_METRICS = [
    "value_score_pct", "completion_rate_pct", "energy_total_wh", "min_soc_pct", "latency_mean_min",
    "alert_latency_mean_min", "downlink_util_pct", "storage_peak_pct",
]


ABLATIONS: dict[str, dict[str, bool]] = {
    "full_engine": {},
    "no_prices": {"use_prices": False},
    "no_storage_price": {"price_storage": False},
    "no_queue_pass": {"queue_aware": False},
    "no_battery_guard": {"battery_guard": False},
}


def run_one(job: tuple[str, str, int]) -> Row:
    scenario_name, policy_name, seed = job
    result = run_simulation(get_scenario(scenario_name), make_policy(policy_name), seed)
    return {"scenario": scenario_name, "policy": policy_name, "seed": seed, **compute_metrics(result)}


def run_variant(job: tuple[str, str, int]) -> Row:
    """One value-aware run with some engine components switched off (ablation study)."""
    scenario_name, variant, seed = job
    policy = ValueAwarePolicy(ValueAwareConfig(**ABLATIONS[variant]))
    result = run_simulation(get_scenario(scenario_name), policy, seed)
    return {"scenario": scenario_name, "policy": variant, "seed": seed, **compute_metrics(result)}


def run_ablation(scenarios: Iterable[str], seeds: Iterable[int], workers: int | None = None) -> list[Row]:
    jobs = [(s, v, seed) for s in scenarios for v in ABLATIONS for seed in seeds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1:
        rows = [run_variant(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(run_variant, jobs, chunksize=1))
    return sorted(rows, key=lambda r: (str(r["scenario"]), str(r["policy"]), int(r["seed"])))


def run_grid(
    scenarios: Iterable[str], policies: Iterable[str], seeds: Iterable[int], workers: int | None = None
) -> list[Row]:
    jobs = [(s, p, seed) for s in scenarios for p in policies for seed in seeds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    log.info("running %d simulations on %d workers", len(jobs), workers)
    if workers == 1:
        rows = [run_one(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(run_one, jobs, chunksize=1))
    return sorted(rows, key=lambda r: (str(r["scenario"]), str(r["policy"]), int(r["seed"])))


def _mean_ci(values: Sequence[float]) -> tuple[float, float]:
    arr = np.array([v for v in values if isinstance(v, (int, float)) and math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan")
    ci = 1.96 * arr.std(ddof=1) / math.sqrt(arr.size) if arr.size > 1 else 0.0
    return float(arr.mean()), float(ci)


def summarize(rows: list[Row], metrics: list[str] | None = None) -> list[Row]:
    """Mean and 95% confidence half-width per (scenario, policy)."""
    metrics = metrics or HEADLINE
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        groups[(str(r["scenario"]), str(r["policy"]))].append(r)
    out: list[Row] = []
    for (scenario, policy), members in sorted(groups.items()):
        summary: Row = {"scenario": scenario, "policy": policy, "n_seeds": len(members)}
        for m in metrics:
            mean, ci = _mean_ci([float(x[m]) for x in members])
            summary[m] = mean
            summary[f"{m}_ci95"] = ci
        out.append(summary)
    return out


def gain_over(summary: list[Row], reference: str, candidate: str = "value_aware", metric: str = "value_score_pct") -> dict[str, float]:
    """Relative improvement (%) of the candidate over a reference policy, per scenario."""
    by_key = {(r["scenario"], r["policy"]): float(r[metric]) for r in summary}
    scenarios = sorted({str(r["scenario"]) for r in summary})
    return {
        s: 100.0 * (by_key[(s, candidate)] - by_key[(s, reference)]) / by_key[(s, reference)]
        for s in scenarios
        if (s, candidate) in by_key and (s, reference) in by_key and by_key[(s, reference)] > 0
    }


def to_markdown(summary: list[Row], metrics: list[str]) -> str:
    cols = ["scenario", "policy"] + metrics
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in summary:
        cells = [str(row["scenario"]), str(row["policy"])]
        for m in metrics:
            mean, ci = float(row[m]), float(row.get(f"{m}_ci95", float("nan")))
            cells.append(f"{mean:.1f} ± {ci:.1f}" if math.isfinite(ci) else f"{mean:.1f}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[Row]:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [{k: _parse(v) for k, v in r.items()} for r in rows]


def _parse(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


def save_results(rows: list[Row], outdir: Path) -> list[Row]:
    summary = summarize(rows)
    write_csv(rows, outdir / "runs.csv")
    write_csv(summary, outdir / "summary.csv")
    (outdir / "summary.md").write_text(to_markdown(summary, MARKDOWN_METRICS), encoding="utf-8")
    return summary
