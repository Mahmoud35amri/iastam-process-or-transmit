from dataclasses import replace

import pytest

from satsched.config import Processor
from satsched.scenarios import OPTICAL, SCENARIOS, get_scenario


def test_all_benchmark_scenarios_are_valid():
    for scenario in SCENARIOS.values():
        assert scenario.data_types
        assert scenario.satellite.reserve_wh > scenario.satellite.critical_wh


@pytest.mark.parametrize(
    "changes",
    [
        {"product_ratio": 1.5},  # a product larger than the raw data would bypass storage checks
        {"product_ratio": 0.0},
        {"p_useful": 1.2},
        {"retention": -0.1},
        {"junk_value_frac": 2.0},
        {"raw_size_mb": 0.0},
        {"half_life_s": 0.0},
        {"proc_time_s": -1.0},
    ],
)
def test_invalid_data_types_are_rejected(changes):
    with pytest.raises(ValueError):
        replace(OPTICAL, **changes)


def test_unknown_names_raise_helpful_errors():
    with pytest.raises(KeyError, match="unknown scenario"):
        get_scenario("mars")
    with pytest.raises(KeyError, match="unknown data type"):
        get_scenario("nominal").data_type("lidar")


def test_processor_helpers():
    sat = get_scenario("nominal").satellite
    assert sat.slots(Processor.GPU) == 1 and sat.slots(Processor.NONE) == 0
    assert sat.power_w(Processor.CPU) == sat.cpu_core_w and sat.power_w(Processor.NONE) == 0.0
