"""Pure state-transition functions. Each returns new objects; inputs are never mutated.

The simulator is the only place where hidden ground truth (item usefulness) is used, and it
enforces every hard constraint regardless of what a policy asks for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Iterable, Mapping

from satsched.config import Processor, SatelliteConfig, Scenario
from satsched.models import DataItem, Stage
from satsched.orbit import OrbitSchedule
from satsched.simulator.resources import free_ram_mb, free_slots
from satsched.valuation import realized_value

EPS = 1e-9


@dataclass(frozen=True)
class Storage:
    """Onboard mass memory: the active items and their total footprint."""

    capacity_mb: float
    items: Mapping[int, DataItem]
    used_mb: float

    @staticmethod
    def empty(capacity_mb: float) -> "Storage":
        return Storage(capacity_mb, MappingProxyType({}), 0.0)

    @property
    def free_mb(self) -> float:
        return self.capacity_mb - self.used_mb

    def updated(self, changed: Iterable[DataItem] = (), removed: Iterable[int] = ()) -> "Storage":
        items = dict(self.items)
        used = self.used_mb
        for item_id in removed:
            old = items.pop(item_id, None)
            if old is not None:
                used -= old.size_mb
        for it in changed:
            old = items.get(it.id)
            used += it.size_mb - (old.size_mb if old else 0.0)
            items[it.id] = it
        return Storage(self.capacity_mb, MappingProxyType(items), max(used, 0.0))


def _finish(item: DataItem, stage: Stage, t: float, value: float = 0.0) -> DataItem:
    return replace(item, stage=stage, finished_s=t, value=value)


def admit_arrivals(storage: Storage, arrivals: Iterable[DataItem]) -> tuple[Storage, list[DataItem]]:
    accepted, lost = [], []
    free = storage.free_mb
    for it in arrivals:
        if it.size_mb <= free + EPS:
            accepted.append(it)
            free -= it.size_mb
        else:
            lost.append(_finish(it, Stage.OVERFLOW, it.created_s))
    return storage.updated(accepted), lost


def apply_drops(storage: Storage, ids: Iterable[int], t: float) -> tuple[Storage, list[DataItem]]:
    dropped = [
        _finish(storage.items[i], Stage.DROPPED, t)
        for i in dict.fromkeys(ids)
        if i in storage.items and storage.items[i].stage is not Stage.PROCESSING
    ]
    return storage.updated(removed=[d.id for d in dropped]), dropped


def start_jobs(storage: Storage, ids: Iterable[int], scenario: Scenario) -> tuple[Storage, tuple[int, ...]]:
    types = scenario.types_by_name
    active = tuple(storage.items.values())
    slots = free_slots(active, scenario)
    ram = free_ram_mb(active, scenario)
    started: list[DataItem] = []
    for i in dict.fromkeys(ids):
        it = storage.items.get(i)
        if it is None or it.stage is not Stage.RAW:
            continue
        kind = types[it.kind]
        if not kind.processable or slots[kind.processor] <= 0 or kind.mem_mb > ram + EPS:
            continue
        slots[kind.processor] -= 1
        ram -= kind.mem_mb
        started.append(replace(it, stage=Stage.PROCESSING, proc_remaining_s=kind.proc_time_s))
    return storage.updated(started), tuple(s.id for s in started)


@dataclass(frozen=True)
class JobResult:
    storage: Storage
    discarded: list[DataItem]
    energy_wh: float
    busy_s: dict[Processor, float]
    stalled: int


def run_jobs(
    storage: Storage, t: float, dt: float, scenario: Scenario, truth: Mapping[int, bool], budget_wh: float
) -> JobResult:
    """Advance running jobs by dt, oldest first, while the discretionary energy budget lasts."""
    types = scenario.types_by_name
    sat = scenario.satellite
    changed, discarded = [], []
    busy = {Processor.CPU: 0.0, Processor.GPU: 0.0}
    energy, stalled = 0.0, 0
    for it in sorted((i for i in storage.items.values() if i.stage is Stage.PROCESSING), key=lambda i: i.id):
        kind = types[it.kind]
        run_s = min(dt, it.proc_remaining_s)
        need = sat.power_w(kind.processor) * run_s / 3600.0
        if need > budget_wh - energy + EPS:
            stalled += 1
            continue
        energy += need
        busy[kind.processor] += run_s
        remaining = it.proc_remaining_s - run_s
        if remaining > EPS:
            changed.append(replace(it, proc_remaining_s=remaining))
        elif truth[it.id]:
            size = it.raw_size_mb * kind.product_ratio
            changed.append(
                replace(it, stage=Stage.PRODUCT, processed=True, size_mb=size, sent_mb=0.0, proc_remaining_s=0.0)
            )
        else:
            discarded.append(replace(_finish(it, Stage.DISCARDED, t + run_s), processed=True, size_mb=0.0))
    new_storage = storage.updated(changed, removed=[d.id for d in discarded])
    return JobResult(new_storage, discarded, energy, busy, stalled)


@dataclass(frozen=True)
class TxResult:
    storage: Storage
    delivered: list[DataItem]
    sent_mb: float
    capacity_mb: float
    energy_wh: float


def transmit(
    storage: Storage,
    ids: Iterable[int],
    t: float,
    dt: float,
    schedule: OrbitSchedule,
    truth: Mapping[int, bool],
    scenario: Scenario,
    budget_wh: float,
) -> TxResult:
    """Downlink items in the given priority order during any contact overlapping [t, t + dt)."""
    windows = schedule.windows_between(t, t + dt)
    capacity = schedule.capacity_between(t, t + dt)
    if not windows or capacity <= 0:
        return TxResult(storage, [], 0.0, 0.0, 0.0)
    window = windows[0]
    radio_w = scenario.satellite.radio_w
    energy_cap = max(budget_wh, 0.0) / radio_w * 3600.0 * window.rate_mb_s if radio_w > 0 else capacity
    budget_mb = min(capacity, energy_cap)
    tx_start = max(t, window.start_s)
    types = scenario.types_by_name
    changed, delivered = [], []
    sent = 0.0
    for i in dict.fromkeys(ids):
        if budget_mb - sent <= EPS:
            break
        it = storage.items.get(i)
        if it is None or it.stage not in (Stage.RAW, Stage.PRODUCT):
            continue
        amount = min(it.remaining_mb, budget_mb - sent)
        sent += amount
        if it.remaining_mb - amount <= EPS:
            done_s = tx_start + sent / window.rate_mb_s
            value = realized_value(it, types[it.kind], truth[it.id], done_s)
            delivered.append(replace(_finish(it, Stage.DELIVERED, done_s, value), sent_mb=it.size_mb))
        else:
            changed.append(replace(it, sent_mb=it.sent_mb + amount))
    energy = radio_w * (sent / window.rate_mb_s) / 3600.0
    new_storage = storage.updated(changed, removed=[d.id for d in delivered])
    return TxResult(new_storage, delivered, sent, capacity, energy)


def expire(storage: Storage, t: float, scenario: Scenario) -> tuple[Storage, list[DataItem]]:
    types = scenario.types_by_name
    expired = [
        _finish(it, Stage.EXPIRED, t)
        for it in storage.items.values()
        if it.stage is not Stage.PROCESSING and t - it.created_s > types[it.kind].deadline_s
    ]
    return storage.updated(removed=[e.id for e in expired]), expired


def platform_reserve_wh(schedule: OrbitSchedule, t: float, sat: SatelliteConfig) -> float:
    """Battery energy the platform (base load) still needs to get through the current or next eclipse.

    In sunlight, the solar surplus expected before the eclipse starts is credited against that need.
    """
    if not schedule.is_sunlit(t):
        return sat.base_load_w * (schedule.next_sunrise(t) - t) / 3600.0
    start = schedule.next_eclipse_start(t)
    if not math.isfinite(start):
        return 0.0
    need = sat.base_load_w * (schedule.next_sunrise(start) - start) / 3600.0
    surplus = max(sat.solar_w - sat.base_load_w, 0.0) * (start - t) / 3600.0
    return max(need - surplus, 0.0)


def discretionary_budget_wh(
    soc_wh: float, sat: SatelliteConfig, solar_wh: float, base_wh: float, platform_reserve: float = 0.0
) -> float:
    """Energy the power system lets processing and radio use this step (load shedding).

    Loads are shed before the battery would drop below the critical floor plus the energy the
    platform needs to survive the next eclipse, so the base load can always be supplied.
    """
    return max(soc_wh + solar_wh - base_wh - sat.critical_wh - platform_reserve, 0.0)


def update_soc(
    soc_wh: float, sat: SatelliteConfig, solar_wh: float, base_wh: float, used_wh: float
) -> tuple[float, float, float]:
    """Returns (new state of charge, solar energy spilled because the battery is full, unmet load).

    Unmet load (a brownout) means the platform itself lost power; it must stay zero.
    """
    raw = soc_wh + solar_wh - base_wh - used_wh
    spilled = max(raw - sat.battery_wh, 0.0)
    deficit = max(-raw, 0.0)
    return min(max(raw, 0.0), sat.battery_wh), spilled, deficit
