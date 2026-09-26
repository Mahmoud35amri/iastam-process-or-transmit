from dataclasses import replace

import numpy as np
import pytest

from satsched.models import Observation
from satsched.orbit import ContactWindow, OrbitSchedule
from satsched.policies.pricing import (
    NONE,
    PROCESS,
    RAW,
    OptionBook,
    choose,
    downlink_supply_mb,
    energy_budget_wh,
    energy_headroom_wh,
    inflow_rate_mb_s,
    solve_prices,
    usage,
)
from satsched.scenarios import get_scenario

SCN = get_scenario("nominal")
SAT = SCN.satellite
SCHED = OrbitSchedule(
    period_s=5700.0,
    eclipse_s=2100.0,
    windows=(ContactWindow(1000.0, 1600.0, 10.0), ContactWindow(6700.0, 7200.0, 10.0), ContactWindow(12400.0, 12900.0, 10.0)),
)
BLOCKED = -1e18


def obs(t=0.0, soc=60.0):
    return Observation(t, 30.0, soc, 0.0, (), SCN, SCHED)


def book(raw_values, raw_uses, proc_values, proc_uses, supply):
    """uses given per option as list of per-item resource vectors [bw, energy]."""
    values = np.array([raw_values, proc_values], dtype=float)
    uses = np.array([np.array(raw_uses, float).T, np.array(proc_uses, float).T])
    return OptionBook(values=values, uses=uses, supply=np.array(supply, float))


def test_prices_stay_zero_when_supply_suffices():
    b = book([10, 5], [[1, 0], [1, 0]], [BLOCKED, BLOCKED], [[0, 0], [0, 0]], supply=[5, 5])
    prices = solve_prices(b)
    assert np.all(prices == 0)
    choice, _ = choose(b, prices)
    assert list(choice) == [RAW, RAW]


def test_bandwidth_price_moves_low_gain_item_to_processing():
    # item A gains 5 by going raw (+90 MB), item B only 1: with 120 MB only A should go raw
    b = book([10, 10], [[100, 0], [100, 0]], [5, 9], [[10, 1], [10, 1]], supply=[120, 100])
    prices = solve_prices(b)
    choice, _ = choose(b, prices)
    assert list(choice) == [RAW, PROCESS]
    assert usage(b, choice)[0] <= 120
    assert 1 / 90 <= prices[0] <= 5 / 90


def test_energy_price_keeps_the_most_valuable_jobs():
    b = book([0, 0, 0], [[0, 0]] * 3, [5, 3, 1], [[0, 1]] * 3, supply=[100, 2])
    choice, _ = choose(b, solve_prices(b))
    assert list(choice) == [PROCESS, PROCESS, NONE]


def test_negative_supply_blocks_the_resource():
    b = book([0], [[0, 0]], [5], [[0, 1]], supply=[100, -1])
    choice, _ = choose(b, solve_prices(b))
    assert list(choice) == [NONE]


def test_downlink_supply_counts_first_k_windows_from_now():
    assert downlink_supply_mb(SCHED, 0.0, 2) == pytest.approx(6000 + 5000)
    assert downlink_supply_mb(SCHED, 1300.0, 1) == pytest.approx(3000)
    assert downlink_supply_mb(SCHED, 20000.0, 3) == 0.0


def test_energy_budget_adds_harvest_minus_base_load():
    horizon = 5700.0
    expected = 60.0 - SAT.reserve_wh + SAT.solar_w * 3600 / 3600 - SAT.base_load_w * horizon / 3600
    assert energy_budget_wh(obs(0.0, 60.0), horizon, committed_wh=0.0) == pytest.approx(expected)


def test_energy_headroom_in_eclipse_reserves_base_load_until_sunrise():
    t = 4000.0  # eclipse until 5700
    expected = 50.0 - SAT.base_load_w * 1700 / 3600 - SAT.reserve_wh - 1.0
    assert energy_headroom_wh(obs(t, 50.0), committed_wh=1.0) == pytest.approx(expected)


def test_energy_headroom_reserves_radio_for_a_pass_before_sunrise():
    with_pass = OrbitSchedule(5700.0, 2100.0, (ContactWindow(4200.0, 4800.0, 10.0),))
    o = Observation(4000.0, 30.0, 50.0, 0.0, (), SCN, with_pass)
    expected = 50.0 - SAT.base_load_w * 1700 / 3600 - SAT.radio_w * 600 / 3600 - SAT.reserve_wh
    assert energy_headroom_wh(o, 0.0) == pytest.approx(expected)


def test_energy_headroom_in_sun_accounts_for_next_eclipse():
    t = 3000.0  # sun until 3600, eclipse 3600..5700
    surplus = (SAT.solar_w - SAT.base_load_w) * 600 / 3600
    need = SAT.base_load_w * 2100 / 3600
    assert energy_headroom_wh(obs(t, 50.0), 0.0) == pytest.approx(50.0 + surplus - need - SAT.reserve_wh)


def test_inflow_rate_is_positive_and_scales_with_rates():
    base = inflow_rate_mb_s(SCN)
    doubled = replace(SCN, data_types=tuple(replace(k, rate_per_orbit=2 * k.rate_per_orbit) for k in SCN.data_types))
    assert base > 0
    assert inflow_rate_mb_s(doubled) == pytest.approx(2 * base)
