"""Real orbit geometry: ground-station passes and eclipses from a TLE, computed with skyfield.

`compute_geometry` (needs the optional `skyfield` package and a JPL ephemeris) propagates a real
satellite with SGP4 and saves passes and eclipses to data/orbit/<name>/. The simulator only reads
those CSV files, so skyfield is not needed to run experiments. Each seed simulates a different
real day of the computed span.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from satsched.config import OrbitConfig
from satsched.orbit import DAY_S, ContactWindow, OrbitSchedule

ORBIT_DIR = Path(__file__).resolve().parents[2] / "data" / "orbit"


@dataclass(frozen=True)
class GroundStation:
    name: str
    lat_deg: float
    lon_deg: float
    elevation_m: float


# Approximate site coordinates (city level is ample for pass prediction).
GROUND_STATIONS = {
    "toulouse": GroundStation("CNES Toulouse, France (approx.)", 43.56, 1.48, 150.0),
    "kiruna": GroundStation("Esrange/Kiruna, Sweden (approx.)", 67.88, 21.07, 330.0),
    "svalbard": GroundStation("SvalSat, Svalbard (approx.)", 78.23, 15.41, 500.0),
}


@dataclass(frozen=True)
class Geometry:
    meta: dict[str, Any]
    passes: tuple[tuple[float, float, float, float], ...]  # (mask_deg, start_s, end_s, max_elevation_deg)
    eclipses: tuple[tuple[float, float], ...]  # (start_s, end_s)

    @property
    def period_s(self) -> float:
        return float(self.meta["period_s"])

    def usable_days(self, horizon_s: float) -> int:
        """Number of start days whose whole [day, day + horizon) window lies inside the computed span."""
        return max(int(self.meta["days"] - math.ceil(horizon_s / DAY_S)) + 1, 1)


def _path(name: str) -> Path:
    candidate = Path(name)
    return candidate if candidate.is_absolute() or candidate.exists() else ORBIT_DIR / name


def save_geometry(geo: Geometry, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "geometry.json").write_text(json.dumps(geo.meta, indent=2), encoding="utf-8")
    with (directory / "passes.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["mask_deg", "start_s", "end_s", "max_elevation_deg"])
        writer.writerows([[m, round(a, 1), round(b, 1), round(e, 2)] for m, a, b, e in geo.passes])
    with (directory / "eclipses.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["start_s", "end_s"])
        writer.writerows([[round(a, 1), round(b, 1)] for a, b in geo.eclipses])
    return directory


@lru_cache(maxsize=8)
def load_geometry(name: str) -> Geometry:
    directory = _path(name)
    if not (directory / "geometry.json").exists():
        raise FileNotFoundError(f"no orbit geometry at {directory}; run `python -m satsched.cli geometry`")
    meta = json.loads((directory / "geometry.json").read_text(encoding="utf-8"))
    with (directory / "passes.csv").open(encoding="utf-8") as fh:
        passes = tuple(
            (float(r["mask_deg"]), float(r["start_s"]), float(r["end_s"]), float(r["max_elevation_deg"]))
            for r in csv.DictReader(fh)
        )
    with (directory / "eclipses.csv").open(encoding="utf-8") as fh:
        eclipses = tuple((float(r["start_s"]), float(r["end_s"])) for r in csv.DictReader(fh))
    return Geometry(meta=meta, passes=passes, eclipses=eclipses)


def real_schedule(cfg: OrbitConfig, seed: int, horizon_s: float) -> OrbitSchedule:
    """The contact/eclipse schedule of one real day (day = seed modulo usable days), shifted to t = 0."""
    assert cfg.geometry is not None
    geo = load_geometry(cfg.geometry)
    masks = sorted({m for m, *_ in geo.passes})
    if cfg.min_elevation_deg not in masks:
        raise ValueError(f"elevation mask {cfg.min_elevation_deg} not computed; available masks: {masks}")
    offset = (seed % geo.usable_days(horizon_s)) * DAY_S
    end = offset + horizon_s
    windows = tuple(
        ContactWindow(a - offset, min(b, end) - offset, cfg.downlink_mb_s)
        for m, a, b, _ in geo.passes
        if m == cfg.min_elevation_deg and offset <= a < end
    )
    eclipses = tuple((max(a, offset) - offset, min(b, end) - offset) for a, b in geo.eclipses if b > offset and a < end)
    full = [b - a for a, b in geo.eclipses]
    mean_eclipse = float(np.mean(full)) if full else 0.0
    return OrbitSchedule(period_s=geo.period_s, eclipse_s=mean_eclipse, windows=windows, eclipses=eclipses)


# --- computation (optional dependency: skyfield) ------------------------------------------------


def _intervals(flags: np.ndarray, t_s: np.ndarray) -> list[tuple[float, float]]:
    """Contiguous True runs of a sampled boolean, with edges placed mid-way between samples."""
    padded = np.concatenate([[False], flags, [False]])
    edges = np.flatnonzero(np.diff(padded.astype(int)))
    starts, ends = edges[0::2], edges[1::2]
    out = []
    for s, e in zip(starts, ends):
        a = t_s[0] if s == 0 else 0.5 * (t_s[s - 1] + t_s[s])
        b = t_s[-1] if e == len(t_s) else 0.5 * (t_s[e - 1] + t_s[e])
        out.append((float(a), float(b)))
    return out


def compute_geometry(
    tle_lines: tuple[str, str, str],
    station: GroundStation,
    days: int,
    masks: tuple[float, ...] = (10.0, 20.0),
    step_s: float = 10.0,
    ephemeris: Path | None = None,
    start_utc: datetime | None = None,
) -> Geometry:
    from skyfield import __version__ as skyfield_version
    from skyfield.api import EarthSatellite, Loader, wgs84

    ephemeris = ephemeris or ORBIT_DIR / "de421.bsp"
    loader = Loader(str(ephemeris.parent))
    ts = loader.timescale()
    name, line1, line2 = (s.strip() for s in tle_lines)
    sat = EarthSatellite(line1, line2, name, ts)
    epoch = sat.epoch.utc_datetime()
    start = start_utc or datetime(epoch.year, epoch.month, epoch.day, tzinfo=timezone.utc)
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(start + timedelta(days=days))
    site = wgs84.latlon(station.lat_deg, station.lon_deg, elevation_m=station.elevation_m)

    passes: list[tuple[float, float, float, float]] = []
    for mask in masks:
        times, events = sat.find_events(site, t0, t1, altitude_degrees=mask)
        rise = None
        for t, ev in zip(times, events):
            sec = (t.tt - t0.tt) * DAY_S
            if ev == 0:
                rise = sec
            elif ev == 2 and rise is not None:
                mid = ts.tt_jd(t0.tt + (rise + sec) / 2 / DAY_S)
                alt = (sat - site).at(mid).altaz()[0].degrees
                passes.append((float(mask), rise, sec, float(alt)))
                rise = None

    eph = loader(ephemeris.name)
    grid = np.arange(0.0, days * DAY_S + step_s, step_s)
    sunlit = sat.at(ts.tt_jd(t0.tt + grid / DAY_S)).is_sunlit(eph)
    eclipses = _intervals(~np.asarray(sunlit, dtype=bool), grid)

    period_s = DAY_S / (sat.model.no_kozai * 1440.0 / (2 * math.pi))
    meta = {
        "satellite": name,
        "norad_id": int(line1[2:7]),
        "tle": [name, line1, line2],
        "tle_epoch_utc": epoch.isoformat(),
        "start_utc": start.isoformat(),
        "days": days,
        "station": {"name": station.name, "lat_deg": station.lat_deg, "lon_deg": station.lon_deg,
                    "elevation_m": station.elevation_m},
        "masks": list(masks),
        "period_s": round(period_s, 2),
        "sample_step_s": step_s,
        "ephemeris": ephemeris.name,
        "generator": f"skyfield {skyfield_version} (SGP4 propagation, find_events, is_sunlit)",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return Geometry(meta=meta, passes=tuple(sorted(passes, key=lambda p: (p[0], p[1]))), eclipses=tuple(eclipses))
