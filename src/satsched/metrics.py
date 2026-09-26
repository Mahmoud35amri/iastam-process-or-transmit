"""Evaluation metrics, grouped by the five criteria of the problem statement:
decision quality, task completion, energy, latency, resource utilisation."""

from __future__ import annotations

from collections import Counter

import numpy as np

from satsched.models import DataItem, Stage
from satsched.simulator.engine import RunResult
from satsched.valuation import ideal_value

ALERT_KIND = "event_candidate"


def _pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole > 0 else 0.0


def effective_latency_s(item: DataItem, ground_delay_s: float) -> float:
    """Time from acquisition until the data is usable on the ground."""
    assert item.finished_s is not None
    return item.finished_s - item.created_s + (0.0 if item.processed else ground_delay_s)


def _latencies(run: RunResult, items: list[DataItem]) -> np.ndarray:
    types = run.scenario.types_by_name
    return np.array([effective_latency_s(i, types[i.kind].ground_delay_s) for i in items])


def _quality(run: RunResult) -> dict[str, float]:
    types = run.scenario.types_by_name
    ideal = sum(ideal_value(i, types[i.kind], run.truth[i.id]) for i in run.items)
    value = sum(i.value for i in run.items if i.stage is Stage.DELIVERED)
    return {"value_delivered": value, "value_ideal": ideal, "value_score_pct": _pct(value, ideal)}


def _completion(run: RunResult) -> dict[str, float]:
    n = len(run.items)
    stages = Counter(i.stage for i in run.items)
    delivered = [i for i in run.items if i.stage is Stage.DELIVERED]
    return {
        "items_generated": float(n),
        "completion_rate_pct": _pct(stages[Stage.DELIVERED] + stages[Stage.DISCARDED], n),
        "delivered_pct": _pct(stages[Stage.DELIVERED], n),
        "discarded_onboard_pct": _pct(stages[Stage.DISCARDED], n),
        "dropped_pct": _pct(stages[Stage.DROPPED], n),
        "overflow_pct": _pct(stages[Stage.OVERFLOW], n),
        "expired_pct": _pct(stages[Stage.EXPIRED], n),
        "backlog_pct": _pct(sum(stages[s] for s in (Stage.RAW, Stage.PROCESSING, Stage.PRODUCT)), n),
        "processed_onboard_pct": _pct(sum(1 for i in run.items if i.processed), n),
        "sent_raw_pct": _pct(sum(1 for i in delivered if not i.processed), n),
    }


def _energy(run: RunResult, value: float) -> dict[str, float]:
    s, sat = run.series, run.scenario.satellite
    proc, radio = float(s["energy_proc_wh"].sum()), float(s["energy_radio_wh"].sum())
    return {
        "energy_proc_wh": proc,
        "energy_radio_wh": radio,
        "energy_total_wh": proc + radio,
        "wh_per_value": (proc + radio) / value if value > 0 else float("nan"),
        "min_soc_pct": _pct(float(s["soc_wh"].min()), sat.battery_wh),
        "time_below_reserve_pct": 100.0 * float(np.mean(s["soc_wh"] < sat.reserve_wh - 1e-9)),
        "spilled_solar_wh": float(s["spilled_wh"].sum()),
        "brownout_wh": float(s["energy_deficit_wh"].sum()),
        "stalled_job_steps": float(s["stalled_jobs"].sum()),
    }


def _latency(run: RunResult) -> dict[str, float]:
    delivered = [i for i in run.items if i.stage is Stage.DELIVERED]
    lat = _latencies(run, delivered) / 60.0
    alerts = [i for i in delivered if i.kind == ALERT_KIND and run.truth[i.id]]
    alert_lat = _latencies(run, alerts) / 60.0
    true_alerts = sum(1 for i in run.items if i.kind == ALERT_KIND and run.truth[i.id])
    return {
        "latency_mean_min": float(lat.mean()) if lat.size else float("nan"),
        "latency_p95_min": float(np.percentile(lat, 95)) if lat.size else float("nan"),
        "alert_latency_mean_min": float(alert_lat.mean()) if alert_lat.size else float("nan"),
        "alerts_delivered_pct": _pct(len(alerts), true_alerts),
    }


def _utilisation(run: RunResult) -> dict[str, float]:
    s, sc = run.series, run.scenario
    sat, duration = sc.satellite, sc.duration_s
    capacity = float(s["dl_capacity_mb"].sum())
    return {
        "gpu_util_pct": _pct(float(s["gpu_busy_s"].sum()), sat.gpu_slots * duration),
        "cpu_util_pct": _pct(float(s["cpu_busy_s"].sum()), sat.cpu_cores * duration),
        "downlink_util_pct": _pct(float(s["dl_sent_mb"].sum()), capacity),
        "storage_mean_pct": _pct(float(s["storage_mb"].mean()), sat.storage_mb),
        "storage_peak_pct": _pct(float(s["storage_mb"].max()), sat.storage_mb),
    }


def compute_metrics(run: RunResult) -> dict[str, float]:
    quality = _quality(run)
    return {
        **quality,
        **_completion(run),
        **_energy(run, quality["value_delivered"]),
        **_latency(run),
        **_utilisation(run),
    }


def per_type_table(run: RunResult) -> list[dict[str, float | str]]:
    types = run.scenario.types_by_name
    rows = []
    for name, kind in types.items():
        items = [i for i in run.items if i.kind == name]
        delivered = [i for i in items if i.stage is Stage.DELIVERED]
        ideal = sum(ideal_value(i, kind, run.truth[i.id]) for i in items)
        lat = _latencies(run, delivered) / 60.0
        rows.append({
            "data_type": name,
            "generated": len(items),
            "delivered": len(delivered),
            "processed_onboard": sum(1 for i in items if i.processed),
            "sent_raw": sum(1 for i in delivered if not i.processed),
            "value_score_pct": _pct(sum(i.value for i in delivered), ideal),
            "latency_mean_min": float(lat.mean()) if lat.size else float("nan"),
        })
    return rows
