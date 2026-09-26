"""Reference policies the decision engine is compared against."""

from __future__ import annotations

from satsched.models import DataItem, Observation, Plan, Stage


def _fifo(items: tuple[DataItem, ...]) -> list[DataItem]:
    return sorted(items, key=lambda i: (i.created_s, i.id))


class BentPipe:
    """Classic 'store and dump': never process, downlink everything raw, oldest first."""

    name = "bent_pipe"

    def decide(self, obs: Observation) -> Plan:
        queue = [i.id for i in _fifo(obs.items) if i.stage is not Stage.PROCESSING]
        return Plan(downlink=tuple(queue))


class ProcessAll:
    """Greedy onboard processing: process everything processable as soon as possible, FIFO."""

    name = "process_all"

    def decide(self, obs: Observation) -> Plan:
        types = obs.types
        fifo = _fifo(obs.items)
        process = [i.id for i in fifo if i.stage is Stage.RAW and types[i.kind].processable and i.sent_mb == 0]
        downlink = [
            i.id
            for i in fifo
            if i.stage is Stage.PRODUCT or (i.stage is Stage.RAW and not types[i.kind].processable)
        ]
        return Plan(process=tuple(process), downlink=tuple(downlink))


class PriorityRules:
    """Hand-written operations rules: static priority classes, battery thresholds, storage watermark."""

    name = "priority_rules"
    PRIORITY = {"event_candidate": 0, "telemetry": 1, "hyperspectral_cube": 2, "optical_image": 3, "science_log": 4}
    MIN_SOC_TO_PROCESS = {"event_candidate": 0.0, "hyperspectral_cube": 0.5, "optical_image": 0.5, "science_log": 0.7}
    STORAGE_HIGH, STORAGE_TARGET = 0.90, 0.80

    def _rank(self, item: DataItem) -> tuple[int, float, int]:
        return self.PRIORITY.get(item.kind, 9), item.created_s, item.id

    def decide(self, obs: Observation) -> Plan:
        types = obs.types
        soc_frac = obs.soc_wh / obs.scenario.satellite.battery_wh
        ranked = sorted(obs.items, key=self._rank)
        process = [
            i.id
            for i in ranked
            if i.stage is Stage.RAW
            and types[i.kind].processable
            and i.sent_mb == 0
            and soc_frac >= self.MIN_SOC_TO_PROCESS.get(i.kind, 1.0)
        ]
        ready = [i.id for i in ranked if i.stage is Stage.PRODUCT or (i.stage is Stage.RAW and not types[i.kind].processable)]
        spare_fill = [i.id for i in ranked if i.stage is Stage.RAW and types[i.kind].processable]
        return Plan(process=tuple(process), downlink=tuple(ready + spare_fill), drop=self._drops(obs, ranked))

    def _drops(self, obs: Observation, ranked: list[DataItem]) -> tuple[int, ...]:
        capacity = obs.scenario.satellite.storage_mb
        if obs.storage_used_mb <= self.STORAGE_HIGH * capacity:
            return ()
        excess = obs.storage_used_mb - self.STORAGE_TARGET * capacity
        victims = sorted(
            (i for i in ranked if i.stage is Stage.RAW and i.sent_mb == 0),
            key=lambda i: (-self.PRIORITY.get(i.kind, 9), i.created_s, i.id),
        )
        dropped: list[int] = []
        for it in victims:
            if excess <= 0:
                break
            dropped.append(it.id)
            excess -= it.size_mb
        return tuple(dropped)
