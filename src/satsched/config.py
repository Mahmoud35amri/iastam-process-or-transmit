"""Static configuration: satellite hardware, orbit/ground segment and instrument data types.

All values are illustrative orders of magnitude for a small Earth-observation satellite in
low Earth orbit. Units: seconds, megabytes (MB), watts (W), watt-hours (Wh).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Processor(str, Enum):
    CPU = "cpu"
    GPU = "gpu"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class DataType:
    """One class of instrument output and what onboard processing does to it."""

    name: str
    raw_size_mb: float
    base_value: float  # scientific/operational value of a perfect, instantly delivered item
    half_life_s: float  # timeliness: value halves every half_life_s
    deadline_s: float  # value is zero beyond this latency
    rate_per_orbit: float  # mean number of items generated per orbit
    sunlit_only: bool  # optical instruments acquire only on the day side
    p_useful: float  # mean probability that the content is useful (not cloudy / not a false alarm)
    junk_value_frac: float  # value fraction kept by a non-useful item sent raw
    processor: Processor  # unit needed for onboard processing (NONE = not processable)
    proc_time_s: float
    mem_mb: float
    product_ratio: float  # product size / raw size, for useful items
    retention: float  # value fraction kept by the onboard product
    ground_delay_s: float  # extra ground-processing delay when data arrives raw

    def __post_init__(self) -> None:
        fractions = {"p_useful": self.p_useful, "junk_value_frac": self.junk_value_frac, "retention": self.retention}
        for field_name, value in fractions.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{self.name}: {field_name} must be in [0, 1], got {value}")
        # Products must not outgrow the raw data: the simulator does not re-check storage on completion.
        if not 0.0 < self.product_ratio <= 1.0:
            raise ValueError(f"{self.name}: product_ratio must be in (0, 1], got {self.product_ratio}")
        positive = {"raw_size_mb": self.raw_size_mb, "half_life_s": self.half_life_s, "deadline_s": self.deadline_s}
        for field_name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{self.name}: {field_name} must be positive, got {value}")
        if min(self.base_value, self.rate_per_orbit, self.proc_time_s, self.mem_mb, self.ground_delay_s) < 0:
            raise ValueError(f"{self.name}: values, rates, times and memory must be non-negative")

    @property
    def processable(self) -> bool:
        return self.processor is not Processor.NONE


@dataclass(frozen=True, slots=True)
class SatelliteConfig:
    battery_wh: float = 80.0
    initial_soc_frac: float = 0.8
    reserve_frac: float = 0.30  # soft floor the decision engine should respect
    critical_frac: float = 0.10  # hard floor enforced by the power system (loads shed below)
    solar_w: float = 60.0  # array output while sunlit
    base_load_w: float = 22.0  # platform + instruments, always on
    cpu_cores: int = 4
    cpu_core_w: float = 5.0
    gpu_slots: int = 1
    gpu_w: float = 35.0
    ram_mb: float = 8192.0
    storage_mb: float = 32000.0
    radio_w: float = 20.0

    @property
    def reserve_wh(self) -> float:
        return self.battery_wh * self.reserve_frac

    @property
    def critical_wh(self) -> float:
        return self.battery_wh * self.critical_frac

    def slots(self, processor: Processor) -> int:
        return {Processor.CPU: self.cpu_cores, Processor.GPU: self.gpu_slots}.get(processor, 0)

    def power_w(self, processor: Processor) -> float:
        return {Processor.CPU: self.cpu_core_w, Processor.GPU: self.gpu_w}.get(processor, 0.0)


@dataclass(frozen=True, slots=True)
class OrbitConfig:
    period_s: float = 5700.0  # ~95 min LEO orbit
    eclipse_s: float = 2100.0  # ~35 min in Earth's shadow
    clusters_per_day: int = 2  # ground-station visibility comes in clusters of consecutive orbits
    passes_per_cluster: int = 3
    pass_min_s: float = 360.0
    pass_max_s: float = 600.0
    downlink_mb_s: float = 10.0  # 80 Mbit/s X-band
    # Real geometry: name of a data/orbit/<name>/ folder (passes + eclipses from a TLE). None = synthetic.
    geometry: str | None = None
    min_elevation_deg: float = 10.0  # ground-station elevation mask (real geometry only)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    description: str
    satellite: SatelliteConfig
    orbit: OrbitConfig
    data_types: tuple[DataType, ...]
    duration_s: float = 86400.0
    dt_s: float = 30.0

    def data_type(self, name: str) -> DataType:
        for kind in self.data_types:
            if kind.name == name:
                return kind
        raise KeyError(f"unknown data type: {name}")

    @property
    def types_by_name(self) -> dict[str, DataType]:
        return {kind.name: kind for kind in self.data_types}
