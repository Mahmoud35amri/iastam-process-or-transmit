"""Core immutable domain objects shared by the simulator and the policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:  # pragma: no cover
    from satsched.config import DataType, Scenario
    from satsched.orbit import OrbitSchedule


class Stage(str, Enum):
    RAW = "raw"  # stored raw, awaiting a decision
    PROCESSING = "processing"  # running on CPU/GPU
    PRODUCT = "product"  # processed product awaiting downlink
    DELIVERED = "delivered"  # fully received on the ground
    DISCARDED = "discarded"  # processed onboard and found useless (correctly filtered)
    DROPPED = "dropped"  # deleted by the policy
    OVERFLOW = "overflow"  # lost at acquisition: storage full
    EXPIRED = "expired"  # deadline passed while onboard


ACTIVE_STAGES = frozenset({Stage.RAW, Stage.PROCESSING, Stage.PRODUCT})


class Route(str, Enum):
    """The decision taken for an item at a given step."""

    PROCESS_NOW = "process_now"
    STORE = "store"
    TRANSMIT = "transmit"
    DROP = "drop"


@dataclass(frozen=True, slots=True)
class DataItem:
    id: int
    kind: str
    created_s: float
    raw_size_mb: float
    base_value: float
    p_useful: float  # onboard estimate; the true outcome is hidden from policies
    size_mb: float  # current footprint in storage (raw or product)
    stage: Stage = Stage.RAW
    processed: bool = False
    sent_mb: float = 0.0
    proc_remaining_s: float = 0.0
    finished_s: float | None = None
    value: float = 0.0

    @property
    def remaining_mb(self) -> float:
        return max(self.size_mb - self.sent_mb, 0.0)

    @property
    def active(self) -> bool:
        return self.stage in ACTIVE_STAGES


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why the value-aware engine chose a route (for logs, dashboard and paper)."""

    route: Route
    u_process: float
    u_transmit: float
    ev_process: float
    ev_transmit: float
    price_bandwidth: float
    price_energy: float
    reason: str


@dataclass(frozen=True, slots=True)
class Plan:
    """A policy's output for one step. Order matters: earlier ids get resources first."""

    process: tuple[int, ...] = ()
    downlink: tuple[int, ...] = ()
    drop: tuple[int, ...] = ()
    explanations: Mapping[int, Explanation] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Observation:
    """What the onboard computer knows at a step: no hidden ground truth."""

    time_s: float
    dt_s: float
    soc_wh: float
    storage_used_mb: float
    items: tuple[DataItem, ...]  # active items (raw, processing, product)
    scenario: "Scenario"
    schedule: "OrbitSchedule"

    @property
    def types(self) -> dict[str, "DataType"]:
        return self.scenario.types_by_name
