"""Orbit geometry abstraction: eclipses and ground-station contact windows.

Both are predictable onboard (orbit propagation + station list), so policies may use them as forecasts.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

import numpy as np

from satsched.config import OrbitConfig

DAY_S = 86400.0


@dataclass(frozen=True, slots=True)
class ContactWindow:
    start_s: float
    end_s: float
    rate_mb_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def capacity_mb(self) -> float:
        return self.duration_s * self.rate_mb_s


@dataclass(frozen=True)
class OrbitSchedule:
    """Illumination and contact forecasts.

    Two illumination models:
    - periodic (synthetic): each orbit starts sunlit, then enters eclipse for its last `eclipse_s` seconds;
    - explicit (real geometry): `eclipses` lists the shadow intervals computed by orbit propagation,
      and `eclipse_s` is their mean duration (used only for orbit-averaged rates).
    """

    period_s: float
    eclipse_s: float
    windows: tuple[ContactWindow, ...]
    eclipses: tuple[tuple[float, float], ...] | None = None
    _starts: tuple[float, ...] = field(init=False, repr=False, compare=False, default=())
    _ends: tuple[float, ...] = field(init=False, repr=False, compare=False, default=())
    _ecl_starts: tuple[float, ...] = field(init=False, repr=False, compare=False, default=())
    _ecl_ends: tuple[float, ...] = field(init=False, repr=False, compare=False, default=())
    _ecl_cum: tuple[float, ...] = field(init=False, repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "_starts", tuple(w.start_s for w in self.windows))
        object.__setattr__(self, "_ends", tuple(w.end_s for w in self.windows))
        if self.eclipses is not None:
            object.__setattr__(self, "_ecl_starts", tuple(a for a, _ in self.eclipses))
            object.__setattr__(self, "_ecl_ends", tuple(b for _, b in self.eclipses))
            cum = [0.0]
            for a, b in self.eclipses:
                cum.append(cum[-1] + (b - a))
            object.__setattr__(self, "_ecl_cum", tuple(cum))

    @property
    def sun_s(self) -> float:
        return self.period_s - self.eclipse_s

    # --- illumination -------------------------------------------------------------------
    def _eclipse_index(self, t: float) -> int:
        """Index of the explicit eclipse containing t, or -1."""
        i = bisect.bisect_right(self._ecl_starts, t) - 1
        return i if i >= 0 and t < self._ecl_ends[i] else -1

    def is_sunlit(self, t: float) -> bool:
        if self.eclipses is not None:
            return self._eclipse_index(t) < 0
        return (t % self.period_s) < self.sun_s

    def _sun_before(self, t: float) -> float:
        orbits, phase = divmod(t, self.period_s)
        return orbits * self.sun_s + min(phase, self.sun_s)

    def _eclipse_before(self, t: float) -> float:
        i = bisect.bisect_right(self._ecl_starts, t) - 1
        if i < 0:
            return 0.0
        return self._ecl_cum[i] + min(t, self._ecl_ends[i]) - self._ecl_starts[i]

    def sunlit_seconds(self, t0: float, t1: float) -> float:
        if t1 <= t0:
            return 0.0
        if self.eclipses is not None:
            return max((t1 - t0) - (self._eclipse_before(t1) - self._eclipse_before(t0)), 0.0)
        return max(self._sun_before(t1) - self._sun_before(t0), 0.0)

    def next_sunrise(self, t: float) -> float:
        """t itself if sunlit, else the end of the current eclipse."""
        if self.eclipses is not None:
            i = self._eclipse_index(t)
            return t if i < 0 else self._ecl_ends[i]
        if self.is_sunlit(t):
            return t
        return (math.floor(t / self.period_s) + 1) * self.period_s

    def next_eclipse_start(self, t: float) -> float:
        if not self.is_sunlit(t):
            return t
        if self.eclipses is not None:
            i = bisect.bisect_right(self._ecl_starts, t)
            return self._ecl_starts[i] if i < len(self._ecl_starts) else math.inf
        return math.floor(t / self.period_s) * self.period_s + self.sun_s

    def eclipse_intervals(self, t0: float, t1: float) -> tuple[tuple[float, float], ...]:
        """Eclipse intervals clipped to [t0, t1) (for plots and exports)."""
        if self.eclipses is not None:
            spans = self.eclipses
        else:
            first = math.floor(t0 / self.period_s)
            last = math.ceil(t1 / self.period_s)
            spans = tuple((k * self.period_s + self.sun_s, (k + 1) * self.period_s) for k in range(first, last + 1))
        return tuple((max(a, t0), min(b, t1)) for a, b in spans if b > t0 and a < t1)

    # --- contact windows -----------------------------------------------------------------
    def window_at(self, t: float) -> ContactWindow | None:
        idx = bisect.bisect_right(self._starts, t) - 1
        if idx >= 0 and t < self._ends[idx]:
            return self.windows[idx]
        return None

    def next_window(self, t: float) -> ContactWindow | None:
        """The window containing t, or the first one starting after t."""
        idx = bisect.bisect_right(self._ends, t)
        return self.windows[idx] if idx < len(self.windows) else None

    def windows_between(self, t0: float, t1: float) -> tuple[ContactWindow, ...]:
        lo = bisect.bisect_right(self._ends, t0)
        hi = bisect.bisect_left(self._starts, t1)
        return self.windows[lo:hi]

    def capacity_between(self, t0: float, t1: float) -> float:
        total = 0.0
        for w in self.windows_between(t0, t1):
            overlap = min(w.end_s, t1) - max(w.start_s, t0)
            if overlap > 0:
                total += overlap * w.rate_mb_s
        return total

    def time_to_send(self, t0: float, volume_mb: float) -> float:
        """Earliest time at which `volume_mb` can be fully downlinked when starting at t0."""
        if volume_mb <= 0:
            return t0
        remaining = volume_mb
        idx = bisect.bisect_right(self._ends, t0)
        for w in self.windows[idx:]:
            start = max(w.start_s, t0)
            cap = (w.end_s - start) * w.rate_mb_s
            if cap >= remaining:
                return start + remaining / w.rate_mb_s
            remaining -= cap
        return math.inf


def build_schedule(cfg: OrbitConfig, duration_s: float, rng: np.random.Generator) -> OrbitSchedule:
    """Clusters of consecutive-orbit passes, `clusters_per_day` times per day (typical of one station)."""
    windows: list[ContactWindow] = []
    block = DAY_S / cfg.clusters_per_day
    span = cfg.passes_per_cluster * cfg.period_s
    for day in range(math.ceil(duration_s / DAY_S)):
        for cluster in range(cfg.clusters_per_day):
            first = day * DAY_S + cluster * block + rng.uniform(0.0, max(block - span, 0.0))
            for p in range(cfg.passes_per_cluster):
                start = first + p * cfg.period_s + rng.uniform(0.0, 120.0)
                duration = rng.uniform(cfg.pass_min_s, cfg.pass_max_s)
                windows.append(ContactWindow(float(start), float(start + duration), cfg.downlink_mb_s))
    windows.sort(key=lambda w: w.start_s)
    return OrbitSchedule(period_s=cfg.period_s, eclipse_s=cfg.eclipse_s, windows=tuple(windows))
