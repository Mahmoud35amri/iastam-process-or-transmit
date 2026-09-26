from dataclasses import replace

import pytest

from satsched.config import Processor
from satsched.models import DataItem, Stage
from satsched.orbit import ContactWindow, OrbitSchedule
from satsched.scenarios import get_scenario
from satsched.simulator.physics import (
    Storage,
    admit_arrivals,
    apply_drops,
    discretionary_budget_wh,
    expire,
    run_jobs,
    start_jobs,
    transmit,
    update_soc,
)
from satsched.simulator.resources import free_ram_mb, free_slots

SCN = get_scenario("nominal")
SAT = SCN.satellite
WINDOW = ContactWindow(1000.0, 1600.0, 10.0)
SCHEDULE = OrbitSchedule(period_s=5700.0, eclipse_s=2100.0, windows=(WINDOW,))


def mk(id_, kind="optical_image", size=300.0, **kw):
    return DataItem(id=id_, kind=kind, created_s=0.0, raw_size_mb=size, base_value=10.0, p_useful=0.5, size_mb=size, **kw)


def storage_with(*items, capacity=10_000.0):
    return Storage.empty(capacity).updated(items)


def test_storage_tracks_usage():
    s = storage_with(mk(1), mk(2, size=100.0))
    assert s.used_mb == pytest.approx(400.0)
    s2 = s.updated([replace(s.items[1], size_mb=50.0)], removed=[2])
    assert s2.used_mb == pytest.approx(50.0)
    assert s.used_mb == pytest.approx(400.0)  # original untouched
    assert s2.free_mb == pytest.approx(10_000.0 - 50.0)


def test_admit_overflows_when_full():
    s, lost = admit_arrivals(Storage.empty(500.0), (mk(1), mk(2), mk(3, size=100.0)))
    assert set(s.items) == {1, 3}
    assert [i.id for i in lost] == [2]
    assert lost[0].stage is Stage.OVERFLOW


def test_apply_drops_ignores_unknown_and_processing():
    s = storage_with(mk(1), mk(2, stage=Stage.PROCESSING))
    s2, dropped = apply_drops(s, (1, 2, 99), t=50.0)
    assert [d.id for d in dropped] == [1]
    assert dropped[0].stage is Stage.DROPPED and dropped[0].finished_s == 50.0
    assert set(s2.items) == {2}


def test_start_jobs_respects_gpu_slots_and_kinds():
    s = storage_with(mk(1), mk(2), mk(3, kind="telemetry", size=1.0), mk(4, kind="event_candidate", size=40.0))
    s2, started = start_jobs(s, (1, 2, 3, 4), SCN)
    assert started == (1, 4)  # one GPU slot; telemetry is not processable
    assert s2.items[1].stage is Stage.PROCESSING
    assert s2.items[1].proc_remaining_s == SCN.data_type("optical_image").proc_time_s
    assert free_slots(tuple(s2.items.values()), SCN)[Processor.GPU] == 0
    assert free_slots(tuple(s2.items.values()), SCN)[Processor.CPU] == SAT.cpu_cores - 1


def test_start_jobs_respects_ram():
    small_ram = replace(SCN, satellite=replace(SAT, ram_mb=600.0, cpu_cores=4))
    items = [mk(i, kind="event_candidate", size=40.0) for i in range(3)]
    s2, started = start_jobs(storage_with(*items), (0, 1, 2), small_ram)
    assert started == (0,)
    assert free_ram_mb(tuple(s2.items.values()), small_ram) == pytest.approx(600.0 - 512.0)


def test_run_jobs_completes_useful_and_discards_useless():
    kind = SCN.data_type("event_candidate")
    s = storage_with(
        mk(1, kind="event_candidate", size=40.0, stage=Stage.PROCESSING, proc_remaining_s=10.0),
        mk(2, kind="event_candidate", size=40.0, stage=Stage.PROCESSING, proc_remaining_s=10.0),
    )
    res = run_jobs(s, t=0.0, dt=30.0, scenario=SCN, truth={1: True, 2: False}, budget_wh=10.0)
    product = res.storage.items[1]
    assert product.stage is Stage.PRODUCT and product.processed
    assert product.size_mb == pytest.approx(40.0 * kind.product_ratio)
    assert [d.id for d in res.discarded] == [2]
    assert res.discarded[0].stage is Stage.DISCARDED
    assert res.energy_wh == pytest.approx(2 * SAT.cpu_core_w * 10.0 / 3600)
    assert res.busy_s[Processor.CPU] == pytest.approx(20.0)


def test_run_jobs_stalls_without_energy():
    s = storage_with(mk(1, stage=Stage.PROCESSING, proc_remaining_s=90.0))
    res = run_jobs(s, t=0.0, dt=30.0, scenario=SCN, truth={1: True}, budget_wh=0.0)
    assert res.storage.items[1].proc_remaining_s == 90.0
    assert res.stalled == 1
    assert res.energy_wh == 0.0


def test_run_jobs_partial_progress():
    s = storage_with(mk(1, stage=Stage.PROCESSING, proc_remaining_s=90.0))
    res = run_jobs(s, t=0.0, dt=30.0, scenario=SCN, truth={1: True}, budget_wh=10.0)
    assert res.storage.items[1].proc_remaining_s == pytest.approx(60.0)
    assert res.energy_wh == pytest.approx(SAT.gpu_w * 30.0 / 3600)


def test_transmit_outside_window_sends_nothing():
    s = storage_with(mk(1))
    res = transmit(s, (1,), 0.0, 30.0, SCHEDULE, {1: True}, SCN, budget_wh=100.0)
    assert res.sent_mb == 0 and res.capacity_mb == 0 and not res.delivered


def test_transmit_in_window_delivers_in_order_with_partial():
    s = storage_with(mk(1, size=200.0), mk(2, size=200.0), mk(3, stage=Stage.PROCESSING))
    res = transmit(s, (3, 1, 2), 1000.0, 30.0, SCHEDULE, {1: True, 2: True, 3: True}, SCN, budget_wh=100.0)
    assert res.capacity_mb == pytest.approx(300.0)
    assert [d.id for d in res.delivered] == [1]
    assert res.delivered[0].finished_s == pytest.approx(1020.0)
    assert res.delivered[0].value > 0
    assert res.storage.items[2].sent_mb == pytest.approx(100.0)
    assert res.energy_wh == pytest.approx(SAT.radio_w * 30.0 / 3600)
    assert res.storage.used_mb == pytest.approx(200.0 + 300.0)


def test_transmit_limited_by_energy():
    s = storage_with(mk(1, size=200.0))
    budget = SAT.radio_w * 10.0 / 3600  # 10 s of radio
    res = transmit(s, (1,), 1000.0, 30.0, SCHEDULE, {1: True}, SCN, budget_wh=budget)
    assert res.sent_mb == pytest.approx(100.0)


def test_expire_removes_old_items_but_not_processing():
    kind = SCN.data_type("event_candidate")
    s = storage_with(mk(1, kind="event_candidate", size=40.0), mk(2, kind="event_candidate", size=40.0, stage=Stage.PROCESSING))
    s2, expired = expire(s, t=kind.deadline_s + 1.0, scenario=SCN)
    assert [e.id for e in expired] == [1]
    assert set(s2.items) == {2}


def test_update_soc_clamps_and_reports_spill():
    soc, spilled = update_soc(79.0, SAT, solar_wh=5.0, base_wh=1.0, used_wh=1.0)
    assert soc == SAT.battery_wh and spilled == pytest.approx(2.0)
    soc, spilled = update_soc(1.0, SAT, solar_wh=0.0, base_wh=5.0, used_wh=0.0)
    assert soc == 0.0 and spilled == 0.0


def test_discretionary_budget_keeps_critical_floor():
    assert discretionary_budget_wh(SAT.critical_wh, SAT, 0.0, 1.0) == 0.0
    assert discretionary_budget_wh(50.0, SAT, 2.0, 1.0) == pytest.approx(50.0 + 1.0 - SAT.critical_wh)
