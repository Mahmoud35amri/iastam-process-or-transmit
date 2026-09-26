"""Simulation loop: arrivals -> policy decision -> drops -> jobs -> downlink -> energy -> expiry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np

from satsched.config import Processor, Scenario
from satsched.models import DataItem, Explanation, Observation, Plan, Stage
from satsched.geometry import real_schedule
from satsched.orbit import OrbitSchedule, build_schedule
from satsched.simulator import physics as ph
from satsched.workload import Workload, generate_workload

FORECAST_EXTRA_S = 86400.0  # schedule generated beyond the run so forecasts never hit the edge

SERIES_KEYS = (
    "time_s", "soc_wh", "storage_mb", "sunlit", "in_contact", "cpu_busy_s", "gpu_busy_s",
    "energy_proc_wh", "energy_radio_wh", "spilled_wh", "dl_capacity_mb", "dl_sent_mb",
    "n_raw", "n_processing", "n_product", "value_cum", "stalled_jobs", "started_jobs",
)


class Policy(Protocol):
    name: str

    def decide(self, obs: Observation) -> Plan: ...


@dataclass(frozen=True, slots=True)
class Event:
    time_s: float
    item_id: int
    kind: str
    action: str  # process_start | delivered | dropped | overflow | discarded | expired
    value: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class RunResult:
    scenario: Scenario
    policy_name: str
    seed: int
    schedule: OrbitSchedule
    items: tuple[DataItem, ...]  # final state of every generated item
    truth: Mapping[int, bool]
    series: Mapping[str, np.ndarray]
    events: tuple[Event, ...]


def _explain(plan: Plan, item_id: int) -> str:
    exp: Explanation | None = plan.explanations.get(item_id)
    return exp.reason if exp else ""


def _outcome_events(items: list[DataItem], action: str, plan: Plan | None = None) -> list[Event]:
    return [
        Event(i.finished_s or 0.0, i.id, i.kind, action, i.value, _explain(plan, i.id) if plan else "")
        for i in items
    ]


def _stage_counts(storage: ph.Storage) -> tuple[int, int, int]:
    counts = {Stage.RAW: 0, Stage.PROCESSING: 0, Stage.PRODUCT: 0}
    for it in storage.items.values():
        counts[it.stage] += 1
    return counts[Stage.RAW], counts[Stage.PROCESSING], counts[Stage.PRODUCT]


def make_environment(scenario: Scenario, seed: int) -> tuple[OrbitSchedule, Workload]:
    """Contact schedule and instrument workload for a seed (identical for every policy)."""
    rng = np.random.default_rng(seed)
    horizon = scenario.duration_s + FORECAST_EXTRA_S
    if scenario.orbit.geometry:
        schedule = real_schedule(scenario.orbit, seed, horizon)  # one real day per seed
    else:
        schedule = build_schedule(scenario.orbit, horizon, rng)
    return schedule, generate_workload(scenario, schedule, rng)


def run_simulation(scenario: Scenario, policy: Policy, seed: int) -> RunResult:
    schedule, workload = make_environment(scenario, seed)
    arrivals = workload.arrivals_by_step(scenario.dt_s)
    sat, dt = scenario.satellite, scenario.dt_s
    n_steps = int(round(scenario.duration_s / dt))

    storage = ph.Storage.empty(sat.storage_mb)
    soc = sat.battery_wh * sat.initial_soc_frac
    finished: list[DataItem] = []
    events: list[Event] = []
    series = {k: np.zeros(n_steps) for k in SERIES_KEYS}
    value_cum = 0.0

    for step in range(n_steps):
        t = step * dt
        storage, lost = ph.admit_arrivals(storage, arrivals.get(step, ()))
        obs = Observation(t, dt, soc, storage.used_mb, tuple(storage.items.values()), scenario, schedule)
        plan = policy.decide(obs)

        storage, dropped = ph.apply_drops(storage, plan.drop, t)
        storage, started = ph.start_jobs(storage, plan.process, scenario)
        started_kinds = {i: storage.items[i].kind for i in started}
        solar_wh = sat.solar_w * schedule.sunlit_seconds(t, t + dt) / 3600.0
        base_wh = sat.base_load_w * dt / 3600.0
        budget = ph.discretionary_budget_wh(soc, sat, solar_wh, base_wh)
        jobs = ph.run_jobs(storage, t, dt, scenario, workload.truth, budget)
        tx = ph.transmit(jobs.storage, plan.downlink, t, dt, schedule, workload.truth, scenario, budget - jobs.energy_wh)
        soc, spilled = ph.update_soc(soc, sat, solar_wh, base_wh, jobs.energy_wh + tx.energy_wh)
        storage, expired = ph.expire(tx.storage, t + dt, scenario)

        finished += lost + dropped + jobs.discarded + tx.delivered + expired
        events += _outcome_events(lost, "overflow") + _outcome_events(dropped, "dropped", plan)
        events += [Event(t, i, started_kinds[i], "process_start", 0.0, _explain(plan, i)) for i in started]
        events += _outcome_events(jobs.discarded, "discarded") + _outcome_events(tx.delivered, "delivered", plan)
        events += _outcome_events(expired, "expired")
        value_cum += sum(d.value for d in tx.delivered)

        n_raw, n_proc, n_prod = _stage_counts(storage)
        row = {
            "time_s": t, "soc_wh": soc, "storage_mb": storage.used_mb, "sunlit": float(schedule.is_sunlit(t)),
            "in_contact": float(tx.capacity_mb > 0), "cpu_busy_s": jobs.busy_s[Processor.CPU],
            "gpu_busy_s": jobs.busy_s[Processor.GPU], "energy_proc_wh": jobs.energy_wh,
            "energy_radio_wh": tx.energy_wh, "spilled_wh": spilled, "dl_capacity_mb": tx.capacity_mb,
            "dl_sent_mb": tx.sent_mb, "n_raw": n_raw, "n_processing": n_proc, "n_product": n_prod,
            "value_cum": value_cum, "stalled_jobs": jobs.stalled, "started_jobs": len(started),
        }
        for key, val in row.items():
            series[key][step] = val

    items = tuple(sorted(finished + list(storage.items.values()), key=lambda i: i.id))
    return RunResult(scenario, policy.name, seed, schedule, items, workload.truth, series, tuple(events))
