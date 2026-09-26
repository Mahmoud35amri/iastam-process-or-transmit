"""Benchmark scenarios: a nominal mission plus stress cases that make each resource binding."""

from __future__ import annotations

from dataclasses import replace

from satsched.config import DataType, OrbitConfig, Processor, SatelliteConfig, Scenario

HOUR = 3600.0

OPTICAL = DataType(
    name="optical_image", raw_size_mb=300.0, base_value=10.0, half_life_s=6 * HOUR, deadline_s=36 * HOUR,
    rate_per_orbit=12.0, sunlit_only=True, p_useful=0.6, junk_value_frac=0.05,
    processor=Processor.GPU, proc_time_s=90.0, mem_mb=2048.0,
    product_ratio=0.12, retention=0.8, ground_delay_s=1 * HOUR,
)  # cloud screening + compression; cloudy scenes are discarded onboard

HYPERSPECTRAL = DataType(
    name="hyperspectral_cube", raw_size_mb=800.0, base_value=16.0, half_life_s=12 * HOUR, deadline_s=48 * HOUR,
    rate_per_orbit=3.0, sunlit_only=True, p_useful=0.8, junk_value_frac=0.1,
    processor=Processor.GPU, proc_time_s=240.0, mem_mb=6144.0,
    product_ratio=0.08, retention=0.6, ground_delay_s=2 * HOUR,
)  # band selection / feature extraction loses part of the science

EVENT = DataType(
    name="event_candidate", raw_size_mb=40.0, base_value=30.0, half_life_s=1 * HOUR, deadline_s=6 * HOUR,
    rate_per_orbit=6.0, sunlit_only=False, p_useful=0.3, junk_value_frac=0.0,
    processor=Processor.CPU, proc_time_s=10.0, mem_mb=512.0,
    product_ratio=0.025, retention=1.0, ground_delay_s=0.5 * HOUR,
)  # fire / flood / ship detection candidates; most are false alarms

SCIENCE = DataType(
    name="science_log", raw_size_mb=10.0, base_value=1.5, half_life_s=24 * HOUR, deadline_s=72 * HOUR,
    rate_per_orbit=12.0, sunlit_only=False, p_useful=0.9, junk_value_frac=0.5,
    processor=Processor.CPU, proc_time_s=15.0, mem_mb=256.0,
    product_ratio=0.3, retention=0.95, ground_delay_s=1 * HOUR,
)  # radiation / particle monitor records, lossless-ish compression

TELEMETRY = DataType(
    name="telemetry", raw_size_mb=1.0, base_value=1.0, half_life_s=1 * HOUR, deadline_s=6 * HOUR,
    rate_per_orbit=19.0, sunlit_only=False, p_useful=1.0, junk_value_frac=1.0,
    processor=Processor.NONE, proc_time_s=0.0, mem_mb=0.0,
    product_ratio=1.0, retention=1.0, ground_delay_s=0.0,
)  # housekeeping: must be downlinked as is

DATA_TYPES = (OPTICAL, HYPERSPECTRAL, EVENT, SCIENCE, TELEMETRY)

NOMINAL = Scenario(
    name="nominal",
    description="Synthetic geometry: 95-min orbit, 2 clusters of 3 passes/day, ~29 GB/day downlink.",
    satellite=SatelliteConfig(),
    orbit=OrbitConfig(),
    data_types=DATA_TYPES,
)


def _with_types(scenario: Scenario, **changes: dict) -> tuple[DataType, ...]:
    return tuple(replace(k, **changes[k.name]) if k.name in changes else k for k in scenario.data_types)


def _family(base: Scenario, suffix: str, starved_orbit: OrbitConfig) -> dict[str, Scenario]:
    """The five benchmark scenarios built around one base (orbit geometry) configuration."""
    variants = {
        "nominal": base,
        "energy_starved": replace(
            base,
            description="Degraded solar array and smaller battery: processing everything is not affordable.",
            satellite=replace(base.satellite, solar_w=46.0, battery_wh=60.0),
        ),
        "downlink_starved": replace(
            base,
            description="Fewer usable passes and half the data rate: bandwidth is the bottleneck.",
            orbit=starved_orbit,
        ),
        "storage_tight": replace(
            base,
            description="Only 8 GB of mass memory: storing raw data for later is expensive.",
            satellite=replace(base.satellite, storage_mb=8000.0),
        ),
        "event_surge": replace(
            base,
            description="Crisis mode: 5x more time-critical event candidates (e.g. wildfire season).",
            data_types=_with_types(base, event_candidate={"rate_per_orbit": 30.0, "p_useful": 0.4}),
        ),
    }
    return {f"{key}{suffix}": replace(sc, name=f"{key}{suffix}") for key, sc in variants.items()}


# Real orbit geometry (default): Sentinel-2A TLE of 2026-09-26 propagated with skyfield/SGP4,
# CNES Toulouse ground station. Period and mean eclipse from data/orbit/sentinel2a_toulouse/geometry.json.
REAL_ORBIT = replace(
    OrbitConfig(), period_s=6038.5, eclipse_s=2045.0, geometry="sentinel2a_toulouse", min_elevation_deg=10.0
)
REAL_NOMINAL = replace(
    NOMINAL,
    description="Sentinel-2A orbit (real TLE, 786 km SSO) seen from Toulouse: ~4.4 passes/day, ~21 GB/day downlink.",
    orbit=REAL_ORBIT,
)
SCENARIOS: dict[str, Scenario] = _family(
    REAL_NOMINAL, "", replace(REAL_ORBIT, min_elevation_deg=20.0, downlink_mb_s=5.0)
)
SYNTHETIC_SCENARIOS: dict[str, Scenario] = _family(
    NOMINAL, "_synthetic", replace(NOMINAL.orbit, passes_per_cluster=2, downlink_mb_s=5.0)
)
ALL_SCENARIOS: dict[str, Scenario] = {**SCENARIOS, **SYNTHETIC_SCENARIOS}


def get_scenario(name: str) -> Scenario:
    try:
        return ALL_SCENARIOS[name]
    except KeyError as exc:
        raise KeyError(f"unknown scenario '{name}', choose from {sorted(ALL_SCENARIOS)}") from exc
