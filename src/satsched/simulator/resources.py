"""Read-only views of onboard compute resources, shared by the simulator and the policies."""

from __future__ import annotations

from typing import Iterable

from satsched.config import Processor, Scenario
from satsched.models import DataItem, Stage


def _running(items: Iterable[DataItem]) -> list[DataItem]:
    return [i for i in items if i.stage is Stage.PROCESSING]


def free_slots(items: Iterable[DataItem], scenario: Scenario) -> dict[Processor, int]:
    types = scenario.types_by_name
    busy = {Processor.CPU: 0, Processor.GPU: 0}
    for it in _running(items):
        busy[types[it.kind].processor] += 1
    sat = scenario.satellite
    return {p: sat.slots(p) - n for p, n in busy.items()}


def free_ram_mb(items: Iterable[DataItem], scenario: Scenario) -> float:
    types = scenario.types_by_name
    used = sum(types[i.kind].mem_mb for i in _running(items))
    return scenario.satellite.ram_mb - used
