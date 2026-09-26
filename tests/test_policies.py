from dataclasses import replace

import pytest

from satsched.models import DataItem, Observation, Route, Stage
from satsched.orbit import ContactWindow, OrbitSchedule
from satsched.policies import POLICY_NAMES, make_policy
from satsched.policies.baselines import BentPipe, PriorityRules, ProcessAll
from satsched.policies.value_aware import ValueAwareConfig, ValueAwarePolicy
from satsched.scenarios import get_scenario

SCN = get_scenario("nominal")
SAT = SCN.satellite
WINDOWS = (ContactWindow(1000.0, 1600.0, 10.0), ContactWindow(6700.0, 7200.0, 10.0), ContactWindow(12400.0, 12900.0, 10.0))
SCHED = OrbitSchedule(period_s=5700.0, eclipse_s=2100.0, windows=WINDOWS)


def mk(id_, kind, created=0.0, stage=Stage.RAW, p=0.6, value=None, size=None, **kw):
    k = SCN.data_type(kind)
    size = size if size is not None else k.raw_size_mb
    return DataItem(id=id_, kind=kind, created_s=created, raw_size_mb=size, base_value=value or k.base_value,
                    p_useful=p, size_mb=size, stage=stage, **kw)


def observe(items, t=0.0, soc=64.0, scenario=SCN, used=None):
    used = used if used is not None else sum(i.size_mb for i in items)
    return Observation(t, 30.0, soc, used, tuple(items), scenario, SCHED)


def test_registry_builds_every_policy():
    assert set(POLICY_NAMES) == {"bent_pipe", "process_all", "priority_rules", "bandwidth_rules", "value_aware"}
    for name in POLICY_NAMES:
        assert make_policy(name).name == name
    with pytest.raises(KeyError):
        make_policy("nope")


def test_bent_pipe_sends_everything_fifo_and_never_processes():
    items = [mk(2, "optical_image", created=50.0), mk(1, "telemetry", created=10.0),
             mk(3, "event_candidate", stage=Stage.PROCESSING)]
    plan = BentPipe().decide(observe(items))
    assert plan.process == ()
    assert plan.downlink == (1, 2)


def test_process_all_processes_everything_and_sends_products():
    items = [mk(1, "optical_image"), mk(2, "telemetry"), mk(3, "event_candidate", stage=Stage.PRODUCT, processed=True)]
    plan = ProcessAll().decide(observe(items))
    assert plan.process == (1,)
    assert plan.downlink == (2, 3)


def test_priority_rules_gate_processing_on_battery():
    items = [mk(1, "optical_image"), mk(2, "event_candidate")]
    low = PriorityRules().decide(observe(items, soc=0.35 * SAT.battery_wh))
    high = PriorityRules().decide(observe(items, soc=0.9 * SAT.battery_wh))
    assert low.process == (2,)
    assert high.process == (2, 1)
    assert high.downlink[0] == 2 or 2 not in high.downlink


def test_priority_rules_drop_lowest_priority_when_storage_is_high():
    items = [mk(i, "optical_image", created=float(i)) for i in range(4)] + [mk(9, "event_candidate")]
    tiny = replace(SCN, satellite=replace(SAT, storage_mb=1300.0))
    plan = PriorityRules().decide(observe(items, scenario=tiny))
    assert plan.drop and 9 not in plan.drop
    assert plan.drop[0] == 0  # oldest of the lowest priority class first


def test_value_aware_processes_urgent_event_immediately():
    items = [mk(1, "event_candidate", p=0.5)]
    plan = ValueAwarePolicy(ValueAwareConfig(explain=True)).decide(observe(items, t=900.0))
    assert plan.process == (1,)
    assert plan.explanations[1].route is Route.PROCESS_NOW


def test_value_aware_always_downlinks_products_and_telemetry_in_contact():
    items = [mk(1, "telemetry"), mk(2, "event_candidate", stage=Stage.PRODUCT, processed=True, size=1.0)]
    plan = ValueAwarePolicy().decide(observe(items, t=1100.0))
    assert set(plan.downlink) >= {1, 2}
    assert plan.downlink[0] == 2  # far more valuable per MB and urgent


def test_value_aware_sends_raw_when_bandwidth_is_plentiful():
    items = [mk(1, "hyperspectral_cube", p=0.9)]
    plan = ValueAwarePolicy(ValueAwareConfig(explain=True)).decide(observe(items, t=1100.0))
    assert plan.explanations[1].route is Route.TRANSMIT
    assert plan.downlink == (1,)


def test_value_aware_processes_when_bandwidth_is_scarce():
    many = [mk(i, "optical_image", p=0.3 + 0.6 * i / 200, created=float(i)) for i in range(200)]  # 60 GB vs 16 GB
    roomy = replace(SCN, satellite=replace(SAT, storage_mb=200_000.0))  # isolate bandwidth from the storage guard
    plan = ValueAwarePolicy(ValueAwareConfig(explain=True)).decide(
        observe(many, t=100.0, soc=SAT.battery_wh, scenario=roomy)
    )
    routes = [e.route for e in plan.explanations.values()]
    assert Route.DROP not in routes
    assert routes.count(Route.PROCESS_NOW) + routes.count(Route.STORE) > routes.count(Route.TRANSMIT)
    assert len(plan.process) == 1  # a single GPU slot


def test_value_aware_defers_processing_in_eclipse_when_battery_is_low():
    items = [mk(1, "optical_image", p=0.6)]
    low = SAT.reserve_wh + 2.0
    plan = ValueAwarePolicy(ValueAwareConfig(explain=True)).decide(observe(items, t=4000.0, soc=low))
    assert plan.process == ()
    assert plan.explanations[1].route in (Route.STORE, Route.TRANSMIT)


def test_value_aware_drops_worthless_items():
    stale = mk(1, "event_candidate", created=0.0)
    kind = SCN.data_type("event_candidate")
    plan = ValueAwarePolicy().decide(observe([stale], t=kind.deadline_s - 60.0))
    assert plan.drop == (1,)


def test_value_aware_storage_guard_frees_space():
    items = [mk(i, "optical_image", p=0.2 + 0.01 * i, created=float(i)) for i in range(20)]
    tight = replace(SCN, satellite=replace(SAT, storage_mb=6200.0))
    plan = ValueAwarePolicy().decide(observe(items, t=100.0, scenario=tight))
    assert plan.drop
    assert plan.drop[0] == 0  # lowest expected value density goes first


def test_bandwidth_rules_send_raw_when_passes_have_room():
    from satsched.policies.baselines import BandwidthRules

    items = [mk(1, "hyperspectral_cube", p=0.9), mk(2, "optical_image", p=0.8), mk(3, "event_candidate"),
             mk(4, "optical_image", p=0.3)]
    plan = BandwidthRules().decide(observe(items, t=0.0, soc=0.9 * SAT.battery_wh))
    assert 1 not in plan.process and 2 not in plan.process  # plenty of pass capacity: keep them raw
    assert 3 in plan.process  # events are still processed onboard
    assert 4 in plan.process  # likely cloudy: processing filters it
    assert plan.downlink.index(1) < plan.downlink.index(2)  # hyperspectral first (loses most when processed)


def test_bandwidth_rules_fall_back_to_processing_when_passes_are_full():
    from satsched.policies.baselines import BandwidthRules

    many = [mk(i, "optical_image", p=0.8, created=float(i)) for i in range(60)]  # 18 GB vs 11 GB in the next 2 passes
    plan = BandwidthRules().decide(observe(many, t=0.0, soc=0.9 * SAT.battery_wh))
    kept_raw = [i for i in range(60) if i not in plan.process]
    assert 0 < len(kept_raw) < 60
    assert sum(300.0 for _ in kept_raw) <= 0.8 * 11000.0 + 1e-6


def test_value_aware_storage_guard_keeps_small_valuable_items():
    # storage almost full of low-value raw images plus fresh telemetry: drop the images, keep telemetry
    images = [mk(i, "optical_image", p=0.2, created=float(i)) for i in range(20)]
    telemetry = [mk(100 + i, "telemetry", created=50.0) for i in range(30)]
    tight = replace(SCN, satellite=replace(SAT, storage_mb=6100.0))
    plan = ValueAwarePolicy().decide(observe(images + telemetry, t=100.0, scenario=tight))
    assert plan.drop and all(i < 100 for i in plan.drop)


def test_bandwidth_rules_cap_raw_holdings_to_half_the_storage():
    from satsched.policies.baselines import BandwidthRules

    small = replace(SCN, satellite=replace(SAT, storage_mb=3000.0))
    many = [mk(i, "optical_image", p=0.8, created=float(i)) for i in range(9)]
    plan = BandwidthRules().decide(observe(many, t=0.0, soc=0.9 * SAT.battery_wh, scenario=small))
    kept = [i for i in range(9) if i not in plan.process]
    assert len(kept) * 300.0 <= 1500.0


def test_explanations_show_saturated_prices_in_words():
    # storage filled mostly by data that cannot be shrunk: even processing both images cannot free enough
    items = [mk(i, "telemetry", size=500.0, created=float(i)) for i in range(10)]
    items += [mk(20 + i, "optical_image", p=0.6, created=float(i)) for i in range(2)]
    tiny = replace(SCN, satellite=replace(SAT, storage_mb=5550.0))
    plan = ValueAwarePolicy(ValueAwareConfig(explain=True)).decide(observe(items, t=100.0, scenario=tiny))
    text = " ".join(e.reason for e in plan.explanations.values())
    assert "e+" not in text and "saturated" in text
