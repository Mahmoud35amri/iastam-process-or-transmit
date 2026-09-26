import json
from dataclasses import replace

import pytest

from satsched.config import OrbitConfig
from satsched.geometry import GROUND_STATIONS, Geometry, load_geometry, real_schedule, save_geometry

DAY = 86400.0


def tiny_geometry(tmp_path):
    geo = Geometry(
        meta={"satellite": "TEST", "period_s": 6000.0, "days": 4, "masks": [10.0, 20.0]},
        passes=((10.0, 1000.0, 1500.0, 40.0), (20.0, 1100.0, 1400.0, 40.0), (10.0, DAY + 500.0, DAY + 900.0, 15.0),
                (10.0, 3 * DAY + 10.0, 3 * DAY + 400.0, 60.0)),
        eclipses=((3600.0, 5700.0), (DAY + 3600.0, DAY + 5700.0), (2 * DAY + 100.0, 2 * DAY + 2200.0)),
    )
    save_geometry(geo, tmp_path / "test_geo")
    return tmp_path / "test_geo"


def test_save_and_load_roundtrip(tmp_path):
    path = tiny_geometry(tmp_path)
    geo = load_geometry(str(path))
    assert geo.period_s == 6000.0
    assert len(geo.passes) == 4 and len(geo.eclipses) == 3
    assert json.loads((path / "geometry.json").read_text())["satellite"] == "TEST"


def test_real_schedule_shifts_to_the_seed_day_and_filters_mask(tmp_path):
    path = tiny_geometry(tmp_path)
    cfg = replace(OrbitConfig(), geometry=str(path), min_elevation_deg=10.0, downlink_mb_s=7.0)
    s0 = real_schedule(cfg, seed=0, horizon_s=2 * DAY)
    assert [(w.start_s, w.end_s) for w in s0.windows] == [(1000.0, 1500.0), (DAY + 500.0, DAY + 900.0)]
    assert all(w.rate_mb_s == 7.0 for w in s0.windows)
    assert s0.period_s == 6000.0
    assert not s0.is_sunlit(4000.0) and s0.is_sunlit(6000.0)
    s1 = real_schedule(cfg, seed=1, horizon_s=2 * DAY)  # day 1: times shifted by one day
    assert s1.windows[0].start_s == 500.0
    assert s1.eclipses[0] == (3600.0, 5700.0)
    high = real_schedule(replace(cfg, min_elevation_deg=20.0), seed=0, horizon_s=DAY)
    assert [(w.start_s, w.end_s) for w in high.windows] == [(1100.0, 1400.0)]


def test_real_schedule_rejects_unknown_mask(tmp_path):
    path = tiny_geometry(tmp_path)
    with pytest.raises(ValueError, match="mask"):
        real_schedule(replace(OrbitConfig(), geometry=str(path), min_elevation_deg=15.0), 0, DAY)


def test_seed_days_wrap_within_computed_span(tmp_path):
    path = tiny_geometry(tmp_path)
    cfg = replace(OrbitConfig(), geometry=str(path))
    usable = load_geometry(str(path)).usable_days(horizon_s=DAY)
    assert usable == 4  # start days 0..3 all fit a 1-day horizon inside 4 computed days
    assert real_schedule(cfg, seed=usable, horizon_s=DAY).windows == real_schedule(cfg, 0, DAY).windows


def test_ground_stations_have_valid_coordinates():
    for st in GROUND_STATIONS.values():
        assert -90 <= st.lat_deg <= 90 and -180 <= st.lon_deg <= 180


def test_bundled_real_geometry_is_available():
    geo = load_geometry("sentinel2a_toulouse")
    assert geo.meta["norad_id"] == 40697
    assert 5500 < geo.period_s < 6500
    assert geo.usable_days(horizon_s=2 * DAY) >= 44
