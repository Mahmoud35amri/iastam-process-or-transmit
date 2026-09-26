import numpy as np

from satsched.models import Stage
from satsched.orbit import build_schedule
from satsched.scenarios import get_scenario
from satsched.workload import generate_workload


def make(seed=0, name="nominal"):
    scenario = get_scenario(name)
    rng = np.random.default_rng(seed)
    schedule = build_schedule(scenario.orbit, scenario.duration_s * 2, rng)
    return scenario, schedule, generate_workload(scenario, schedule, rng)


def test_workload_is_deterministic():
    _, _, a = make(1)
    _, _, b = make(1)
    assert a.items == b.items
    assert dict(a.truth) == dict(b.truth)


def test_items_are_sorted_unique_and_raw():
    _, _, w = make(2)
    ids = [i.id for i in w.items]
    assert ids == list(range(len(ids)))
    created = [i.created_s for i in w.items]
    assert created == sorted(created)
    assert all(i.stage is Stage.RAW and i.size_mb == i.raw_size_mb for i in w.items)
    assert set(w.truth) == set(ids)


def test_sunlit_only_instruments_respect_daylight():
    scenario, schedule, w = make(3)
    kinds = {k.name: k for k in scenario.data_types}
    for it in w.items:
        if kinds[it.kind].sunlit_only:
            assert schedule.is_sunlit(it.created_s)


def test_arrival_counts_match_configured_rates():
    scenario, _, w = make(4)
    orbits = scenario.duration_s / scenario.orbit.period_s
    for kind in scenario.data_types:
        n = sum(1 for i in w.items if i.kind == kind.name)
        expected = kind.rate_per_orbit * orbits
        assert abs(n - expected) < 5 * np.sqrt(expected) + 2


def test_usefulness_estimates_are_probabilities():
    _, _, w = make(5)
    assert all(0.0 < i.p_useful <= 1.0 for i in w.items)
    telemetry = [i for i in w.items if i.kind == "telemetry"]
    assert telemetry and all(i.p_useful == 1.0 and w.truth[i.id] for i in telemetry)


def test_arrivals_by_step_groups_items():
    scenario, _, w = make(6)
    grouped = w.arrivals_by_step(scenario.dt_s)
    assert sum(len(v) for v in grouped.values()) == len(w.items)
    for step, items in grouped.items():
        assert all(int(i.created_s // scenario.dt_s) == step for i in items)
