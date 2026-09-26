import math

import numpy as np
import pytest

from satsched.config import OrbitConfig
from satsched.orbit import ContactWindow, OrbitSchedule, build_schedule


def make_schedule(windows=()):
    return OrbitSchedule(period_s=6000.0, eclipse_s=2000.0, windows=tuple(windows))


W1 = ContactWindow(1000.0, 1600.0, 10.0)
W2 = ContactWindow(7000.0, 7500.0, 5.0)


def test_sun_comes_first_then_eclipse():
    s = make_schedule()
    assert s.is_sunlit(0)
    assert s.is_sunlit(3999)
    assert not s.is_sunlit(4000)
    assert not s.is_sunlit(5999)
    assert s.is_sunlit(6000)


def test_sunlit_seconds_spans_several_orbits():
    s = make_schedule()
    assert s.sunlit_seconds(0, 6000) == pytest.approx(4000)
    assert s.sunlit_seconds(3000, 7000) == pytest.approx(2000)
    assert s.sunlit_seconds(4100, 5900) == pytest.approx(0)
    assert s.sunlit_seconds(10, 10) == 0


def test_next_sunrise_and_eclipse_start():
    s = make_schedule()
    assert s.next_sunrise(100) == 100
    assert s.next_sunrise(4500) == 6000
    assert s.next_eclipse_start(100) == 4000
    assert s.next_eclipse_start(4500) == 4500


def test_window_capacity_and_duration():
    assert W1.duration_s == 600
    assert W1.capacity_mb == 6000


def test_window_lookup():
    s = make_schedule([W1, W2])
    assert s.window_at(1200) == W1
    assert s.window_at(1600) is None
    assert s.window_at(500) is None
    assert s.next_window(1700) == W2
    assert s.next_window(1200) == W1
    assert s.next_window(8000) is None


def test_capacity_between_partial_overlaps():
    s = make_schedule([W1, W2])
    assert s.capacity_between(0, 10000) == pytest.approx(6000 + 2500)
    assert s.capacity_between(1300, 1400) == pytest.approx(1000)
    assert s.capacity_between(1500, 7100) == pytest.approx(1000 + 500)


def test_time_to_send_walks_windows():
    s = make_schedule([W1, W2])
    assert s.time_to_send(0, 1000) == pytest.approx(1100)
    assert s.time_to_send(1200, 1000) == pytest.approx(1300)
    assert s.time_to_send(0, 6500) == pytest.approx(7100)
    assert s.time_to_send(0, 0) == 0
    assert math.isinf(s.time_to_send(0, 1e9))


def test_build_schedule_is_clustered_sorted_and_bounded():
    cfg = OrbitConfig()
    s = build_schedule(cfg, duration_s=2 * 86400, rng=np.random.default_rng(3))
    assert len(s.windows) == 2 * cfg.clusters_per_day * cfg.passes_per_cluster
    starts = [w.start_s for w in s.windows]
    assert starts == sorted(starts)
    for prev, nxt in zip(s.windows, s.windows[1:]):
        assert prev.end_s <= nxt.start_s
    for w in s.windows:
        assert cfg.pass_min_s <= w.duration_s <= cfg.pass_max_s
        assert w.rate_mb_s == cfg.downlink_mb_s


def test_build_schedule_is_deterministic_for_a_seed():
    cfg = OrbitConfig()
    a = build_schedule(cfg, 86400, np.random.default_rng(7))
    b = build_schedule(cfg, 86400, np.random.default_rng(7))
    assert a == b


# --- explicit eclipse intervals (real orbit geometry) -------------------------------------

REAL = OrbitSchedule(
    period_s=6000.0, eclipse_s=2000.0, windows=(W1,), eclipses=((1000.0, 3000.0), (7000.0, 9000.0))
)


def test_interval_mode_sunlit_and_transitions():
    assert REAL.is_sunlit(500)
    assert not REAL.is_sunlit(1000)
    assert not REAL.is_sunlit(2999)
    assert REAL.is_sunlit(3000)
    assert REAL.next_sunrise(1500) == 3000
    assert REAL.next_sunrise(4000) == 4000
    assert REAL.next_eclipse_start(4000) == 7000
    assert REAL.next_eclipse_start(1500) == 1500
    assert math.isinf(REAL.next_eclipse_start(9500))


def test_interval_mode_sunlit_seconds():
    assert REAL.sunlit_seconds(0, 10000) == pytest.approx(10000 - 4000)
    assert REAL.sunlit_seconds(2000, 8000) == pytest.approx(6000 - 1000 - 1000)
    assert REAL.sunlit_seconds(1200, 1300) == 0


def test_eclipse_intervals_clip_for_both_modes():
    assert REAL.eclipse_intervals(0, 8000) == ((1000.0, 3000.0), (7000.0, 8000.0))
    periodic = make_schedule()
    assert periodic.eclipse_intervals(0, 12000) == ((4000.0, 6000.0), (10000.0, 12000.0))
