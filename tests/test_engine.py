from dataclasses import replace

import numpy as np
import pytest

from satsched.models import Plan, Stage
from satsched.scenarios import get_scenario
from satsched.simulator.engine import run_simulation

# 12 h: with the real Sentinel-2A geometry, day 0 has its first Toulouse pass at ~10.2 h
SHORT = replace(get_scenario("nominal"), duration_s=12 * 3600.0)


class Idle:
    name = "idle"

    def decide(self, obs):
        return Plan()


class SendEverything:
    name = "send_everything"

    def decide(self, obs):
        ids = tuple(i.id for i in sorted(obs.items, key=lambda i: i.created_s) if i.stage is not Stage.PROCESSING)
        return Plan(downlink=ids)


@pytest.fixture(scope="module")
def idle_run():
    tight = replace(SHORT, satellite=replace(SHORT.satellite, storage_mb=8000.0))
    return run_simulation(tight, Idle(), seed=0)


@pytest.fixture(scope="module")
def send_run():
    return run_simulation(SHORT, SendEverything(), seed=0)


def test_every_generated_item_is_accounted_for(send_run):
    ids = [i.id for i in send_run.items]
    assert ids == list(range(len(ids)))
    assert len(ids) == len(send_run.truth)


def test_idle_policy_delivers_nothing_and_overflows(idle_run):
    stages = {i.stage for i in idle_run.items}
    assert Stage.DELIVERED not in stages
    assert Stage.OVERFLOW in stages


def test_physical_invariants_hold(send_run):
    sat = SHORT.satellite
    s = send_run.series
    assert np.all(s["soc_wh"] >= 0) and np.all(s["soc_wh"] <= sat.battery_wh + 1e-9)
    assert np.all(s["storage_mb"] <= sat.storage_mb + 1e-6)
    assert np.all(s["dl_sent_mb"] <= s["dl_capacity_mb"] + 1e-6)
    assert np.all(s["dl_capacity_mb"][s["in_contact"] == 0] == 0)


def test_deliveries_happen_only_during_contact(send_run):
    delivered = [i for i in send_run.items if i.stage is Stage.DELIVERED]
    assert delivered
    for it in delivered:
        w = send_run.schedule.window_at(it.finished_s - 1e-6) or send_run.schedule.window_at(it.finished_s)
        assert w is not None


def test_run_is_deterministic():
    a = run_simulation(SHORT, SendEverything(), seed=3)
    b = run_simulation(SHORT, SendEverything(), seed=3)
    assert a.items == b.items


def test_events_log_terminal_outcomes(send_run):
    actions = {e.action for e in send_run.events}
    assert "delivered" in actions
    terminal = sum(1 for i in send_run.items if not i.active)
    logged = sum(1 for e in send_run.events if e.action in {"delivered", "overflow", "dropped", "discarded", "expired"})
    assert logged == terminal
