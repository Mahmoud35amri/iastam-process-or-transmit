"""Seeded instrument data generator. The generated items + hidden truth form the benchmark dataset."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import numpy as np

from satsched.config import DataType, Scenario
from satsched.models import DataItem
from satsched.orbit import OrbitSchedule

BETA_CONCENTRATION = 4.0  # how sharp the per-item usefulness estimate is around the type mean
SIZE_JITTER = (0.8, 1.2)
VALUE_JITTER = (0.5, 1.5)  # per-target priority from the mission plan


@dataclass(frozen=True)
class Workload:
    items: tuple[DataItem, ...]
    truth: Mapping[int, bool]  # hidden: is the item's content actually useful?

    def arrivals_by_step(self, dt_s: float) -> dict[int, tuple[DataItem, ...]]:
        grouped: dict[int, list[DataItem]] = defaultdict(list)
        for it in self.items:
            grouped[int(it.created_s // dt_s)].append(it)
        return {step: tuple(items) for step, items in grouped.items()}


def _usefulness(kind: DataType, rng: np.random.Generator) -> float:
    if kind.p_useful >= 1.0:
        return 1.0
    a = kind.p_useful * BETA_CONCENTRATION
    b = (1.0 - kind.p_useful) * BETA_CONCENTRATION
    return float(np.clip(rng.beta(a, b), 0.01, 0.99))


def _step_rate(kind: DataType, scenario: Scenario, schedule: OrbitSchedule) -> float:
    active_s = schedule.sun_s if kind.sunlit_only else schedule.period_s
    return kind.rate_per_orbit * scenario.dt_s / active_s


def generate_workload(scenario: Scenario, schedule: OrbitSchedule, rng: np.random.Generator) -> Workload:
    items: list[DataItem] = []
    truth: dict[int, bool] = {}
    rates = {k.name: _step_rate(k, scenario, schedule) for k in scenario.data_types}
    n_steps = int(round(scenario.duration_s / scenario.dt_s))
    for step in range(n_steps):
        t = step * scenario.dt_s
        sunlit = schedule.is_sunlit(t)
        for kind in scenario.data_types:
            if kind.sunlit_only and not sunlit:
                continue
            for _ in range(int(rng.poisson(rates[kind.name]))):
                p = _usefulness(kind, rng)
                size = kind.raw_size_mb * rng.uniform(*SIZE_JITTER)
                item = DataItem(
                    id=len(items),
                    kind=kind.name,
                    created_s=t,
                    raw_size_mb=float(size),
                    base_value=float(kind.base_value * rng.uniform(*VALUE_JITTER)),
                    p_useful=p,
                    size_mb=float(size),
                )
                truth[item.id] = bool(rng.random() < p)
                items.append(item)
    return Workload(items=tuple(items), truth=MappingProxyType(truth))
