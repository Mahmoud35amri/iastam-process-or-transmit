"""Exports: the benchmark dataset (CSV/JSON) and the dashboard/demo payload (data.js)."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from satsched.config import Scenario
from satsched.geometry import load_geometry
from satsched.orbit import OrbitSchedule
from satsched.metrics import compute_metrics, per_type_table
from satsched.policies import POLICY_NAMES, make_policy
from satsched.scenarios import SCENARIOS, get_scenario
from satsched.simulator.engine import RunResult, make_environment, run_simulation

LEVEL_SERIES = ("soc_wh", "storage_mb", "value_cum", "n_raw", "n_processing", "n_product", "in_contact", "sunlit")
FLOW_SERIES = ("dl_sent_mb", "dl_capacity_mb", "energy_proc_wh", "energy_radio_wh", "gpu_busy_s", "cpu_busy_s")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (np.floating, np.integer)):
        return _jsonable(value.item())
    return value


def scenario_dict(scenario: Scenario) -> dict[str, Any]:
    return _jsonable(asdict(scenario))


def eclipses(schedule: OrbitSchedule, duration_s: float) -> list[tuple[float, float]]:
    return [(round(a, 1), round(b, 1)) for a, b in schedule.eclipse_intervals(0.0, duration_s)]


def geometry_meta(scenario: Scenario) -> dict[str, Any]:
    """Provenance of the orbit geometry (real TLE + station, or synthetic)."""
    if not scenario.orbit.geometry:
        return {"source": "synthetic", "period_s": scenario.orbit.period_s, "eclipse_s": scenario.orbit.eclipse_s}
    meta = load_geometry(scenario.orbit.geometry).meta
    keep = ("satellite", "norad_id", "tle_epoch_utc", "start_utc", "station", "period_s", "generator")
    return {"source": "real", "min_elevation_deg": scenario.orbit.min_elevation_deg, **{k: meta[k] for k in keep}}


def _write_rows(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def export_dataset(scenario_names: list[str], seeds: list[int], outdir: Path) -> list[Path]:
    """Items (with hidden ground truth), contact windows and eclipses for each scenario and seed."""
    written: list[Path] = []
    (outdir).mkdir(parents=True, exist_ok=True)
    configs = {name: scenario_dict(get_scenario(name)) for name in scenario_names}
    (outdir / "scenarios.json").write_text(json.dumps(configs, indent=2), encoding="utf-8")
    written.append(outdir / "scenarios.json")
    for name in scenario_names:
        scenario = get_scenario(name)
        for seed in seeds:
            schedule, workload = make_environment(scenario, seed)
            base = outdir / name / f"seed_{seed:03d}"
            items = [
                [i.id, i.kind, i.created_s, round(i.raw_size_mb, 3), round(i.base_value, 4), round(i.p_useful, 4),
                 int(workload.truth[i.id])]
                for i in workload.items
            ]
            _write_rows(base / "items.csv",
                        ["id", "kind", "created_s", "raw_size_mb", "base_value", "p_useful_estimate", "useful_truth"], items)
            windows = [[round(w.start_s, 1), round(w.end_s, 1), w.rate_mb_s] for w in schedule.windows
                       if w.start_s < scenario.duration_s]
            _write_rows(base / "contact_windows.csv", ["start_s", "end_s", "rate_mb_s"], windows)
            _write_rows(base / "eclipses.csv", ["start_s", "end_s"],
                        [list(e) for e in eclipses(schedule, scenario.duration_s)])
            written += [base / "items.csv", base / "contact_windows.csv", base / "eclipses.csv"]
    return written


def _downsample(run: RunResult, every: int) -> dict[str, list[float]]:
    s = run.series
    n = len(s["time_s"]) // every * every
    out: dict[str, list[float]] = {"t_min": (s["time_s"][:n:every] / 60.0).round(1).tolist()}
    for key in LEVEL_SERIES:
        out[key] = np.round(s[key][:n:every], 3).tolist()
    for key in FLOW_SERIES:
        out[key] = np.round(s[key][:n].reshape(-1, every).sum(axis=1), 3).tolist()
    return out


def _policy_payload(run: RunResult, every: int) -> dict[str, Any]:
    return {
        "metrics": _jsonable(compute_metrics(run)),
        "per_type": _jsonable(per_type_table(run)),
        "outcomes": dict(Counter(i.stage.value for i in run.items)),
        "series": _downsample(run, every),
    }


def _decisions(run: RunResult, limit: int) -> list[dict[str, Any]]:
    keep = [e for e in run.events if e.detail or e.action in ("discarded", "overflow")]
    return [
        {"t": round(e.time_s / 60.0, 1), "id": e.item_id, "kind": e.kind, "action": e.action,
         "value": round(e.value, 3), "why": e.detail}
        for e in keep[:limit]
    ]


def build_demo(scenario_name: str, seed: int, every: int = 4, benchmark: list[dict] | None = None,
               decision_limit: int = 4000) -> dict[str, Any]:
    scenario = get_scenario(scenario_name)
    runs = {name: run_simulation(scenario, make_policy(name, explain=(name == "value_aware")), seed)
            for name in POLICY_NAMES}
    schedule = runs["value_aware"].schedule
    return {
        "scenario": scenario_dict(scenario),
        "scenarios": {name: SCENARIOS[name].description for name in SCENARIOS},
        "seed": seed,
        "windows": [[round(w.start_s / 60, 2), round(w.end_s / 60, 2), w.rate_mb_s] for w in schedule.windows
                    if w.start_s < scenario.duration_s],
        "eclipses": [[round(a / 60, 2), round(b / 60, 2)] for a, b in eclipses(schedule, scenario.duration_s)],
        "geometry": _jsonable(geometry_meta(scenario)),
        "policies": {name: _policy_payload(run, every) for name, run in runs.items()},
        "decisions": _decisions(runs["value_aware"], decision_limit),
        "benchmark": _jsonable(benchmark or []),
    }


def write_demo_js(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("window.SATSCHED_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    return path
