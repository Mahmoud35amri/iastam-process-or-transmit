"""Shadow prices for scarce onboard resources, found by dual decomposition.

Every candidate item has two options, RAW (transmit as is) and PROCESS (process then transmit
the product), or NONE (keep it for later / let it go). Each option has an expected value and
consumes resources: downlink MB, energy Wh, GPU seconds and CPU seconds over the planning
horizon, and storage MB until the next pass. Given prices lambda, an item picks the option with the best net utility
    U = value - sum_r lambda_r * use_r        (or NONE if every U <= 0).
Prices are raised, by coordinate-wise geometric bisection, until each resource's total planned
use fits its forecast supply. The result is a Lagrangian-relaxation solution of the
multi-choice knapsack: cheap, explainable, and re-solved at every step (receding horizon).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from satsched.config import Scenario
from satsched.models import Observation
from satsched.orbit import OrbitSchedule

RESOURCES = ("bandwidth_mb", "energy_wh", "gpu_s", "cpu_s", "storage_mb")
NONE, RAW, PROCESS = -1, 0, 1
BLOCKED = -1e18  # value of an option that does not exist (e.g. processing telemetry)
_EPS = 1e-9


@dataclass(frozen=True)
class OptionBook:
    values: np.ndarray  # (2, n): expected value of RAW and PROCESS options
    uses: np.ndarray  # (2, R, n): resource consumption of each option
    supply: np.ndarray  # (R,): forecast availability of each resource over the horizon

    @property
    def n(self) -> int:
        return self.values.shape[1]


def utilities(book: OptionBook, prices: np.ndarray) -> np.ndarray:
    return book.values - np.einsum("orn,r->on", book.uses, prices)


def choose(book: OptionBook, prices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best option per item (NONE when no option has positive utility) and the utility matrix."""
    u = utilities(book, prices)
    if book.n == 0:
        return np.zeros(0, dtype=int), u
    best = np.argmax(u, axis=0)
    best_u = u[best, np.arange(book.n)]
    return np.where(best_u > _EPS, best, NONE), u


def usage(book: OptionBook, choice: np.ndarray) -> np.ndarray:
    total = np.zeros(book.supply.shape[0])
    for option in (RAW, PROCESS):
        mask = choice == option
        if mask.any():
            total += book.uses[option][:, mask].sum(axis=1)
    return total


_MAX_DOUBLINGS = 60
SATURATED_PRICE = 1e6  # prices above this mean 'no price clears the resource' (shown as saturated)


def _price_ceiling(book: OptionBook, r: int) -> float:
    """First guess for a price that clears resource r; refined upwards by doubling.

    Uses may be negative: an option can free a resource (processing shrinks what sits in storage).
    """
    use = np.abs(book.uses[:, r, :])
    vals = np.abs(book.values)
    mask = (use > _EPS) & (vals < abs(BLOCKED) / 2)
    if not mask.any():
        return 0.0
    return float((vals[mask] / use[mask]).max()) * 1.01 + _EPS


def _bisect_price(book: OptionBook, prices: np.ndarray, r: int, iterations: int) -> float:
    def used(lam: float) -> float:
        trial = prices.copy()
        trial[r] = lam
        return usage(book, choose(book, trial)[0])[r]

    supply = book.supply[r]
    if used(0.0) <= supply + _EPS:
        return 0.0
    hi = _price_ceiling(book, r)
    if hi <= 0:
        return 0.0
    for _ in range(_MAX_DOUBLINGS):
        if used(hi) <= supply + _EPS:
            break
        hi *= 2.0
    else:
        return hi  # no price clears it (e.g. not enough space can be freed): saturate
    lo = hi * 1e-7
    if used(lo) <= supply + _EPS:
        return lo
    for _ in range(iterations):
        mid = float(np.sqrt(lo * hi))
        if used(mid) <= supply + _EPS:
            hi = mid
        else:
            lo = mid
    return hi


def solve_prices(book: OptionBook, rounds: int = 2, iterations: int = 18) -> np.ndarray:
    prices = np.zeros(book.supply.shape[0])
    if book.n == 0:
        return prices
    for _ in range(rounds):
        for r in range(prices.shape[0]):
            updated = prices.copy()
            updated[r] = _bisect_price(book, prices, r, iterations)
            prices = updated
    return prices


# --- supply forecasts ---------------------------------------------------------------------


def downlink_supply_mb(schedule: OrbitSchedule, t: float, n_windows: int) -> float:
    upcoming = schedule.windows_between(t, float("inf"))[:n_windows]
    return sum((w.end_s - max(w.start_s, t)) * w.rate_mb_s for w in upcoming)


def horizon_end_s(schedule: OrbitSchedule, t: float, n_windows: int) -> float:
    upcoming = schedule.windows_between(t, float("inf"))[:n_windows]
    return upcoming[-1].end_s if upcoming else t


def energy_budget_wh(obs: Observation, horizon_s: float, committed_wh: float) -> float:
    """Discretionary energy over the horizon while ending above the reserve."""
    sat, sched, t = obs.scenario.satellite, obs.schedule, obs.time_s
    harvest = sat.solar_w * sched.sunlit_seconds(t, t + horizon_s) / 3600.0
    base = sat.base_load_w * horizon_s / 3600.0
    return obs.soc_wh - sat.reserve_wh + harvest - base - committed_wh


def radio_need_wh(obs: Observation, until_s: float) -> float:
    """Radio energy for contact time between now and `until_s` (passes must not be starved)."""
    sat, sched, t = obs.scenario.satellite, obs.schedule, obs.time_s
    seconds = sum(min(w.end_s, until_s) - max(w.start_s, t) for w in sched.windows_between(t, until_s))
    return sat.radio_w * max(seconds, 0.0) / 3600.0


def energy_headroom_wh(obs: Observation, committed_wh: float) -> float:
    """Energy that can be spent right now while staying above the reserve through the next eclipse,
    including the radio energy of any pass before the next sunrise."""
    sat, sched, t = obs.scenario.satellite, obs.schedule, obs.time_s
    if sched.is_sunlit(t):
        eclipse_start = sched.next_eclipse_start(t)
        sunrise = sched.next_sunrise(eclipse_start)
        surplus = (sat.solar_w - sat.base_load_w) * (eclipse_start - t) / 3600.0
        need = sat.base_load_w * (sunrise - eclipse_start) / 3600.0 + radio_need_wh(obs, sunrise)
        return obs.soc_wh + surplus - need - sat.reserve_wh - committed_wh
    sunrise = sched.next_sunrise(t)
    need = sat.base_load_w * (sunrise - t) / 3600.0 + radio_need_wh(obs, sunrise)
    return obs.soc_wh - need - sat.reserve_wh - committed_wh


def inflow_rate_mb_s(scenario: Scenario) -> float:
    """Peak (day-side) raw data acquisition rate."""
    orbit = scenario.orbit
    sun_s = orbit.period_s - orbit.eclipse_s
    return sum(
        k.rate_per_orbit * k.raw_size_mb / (sun_s if k.sunlit_only else orbit.period_s) for k in scenario.data_types
    )


def mean_inflow_rate_mb_s(scenario: Scenario) -> float:
    """Orbit-averaged raw data acquisition rate."""
    return sum(k.rate_per_orbit * k.raw_size_mb for k in scenario.data_types) / scenario.orbit.period_s


def processed_footprint_frac(scenario: Scenario) -> float:
    """Fraction of the raw inflow that remains in storage if everything processable is processed."""
    total = sum(k.rate_per_orbit * k.raw_size_mb for k in scenario.data_types)
    kept = sum(
        k.rate_per_orbit * k.raw_size_mb * (k.p_useful * k.product_ratio if k.processable else 1.0)
        for k in scenario.data_types
    )
    return kept / total if total > 0 else 1.0


def arrival_value_density(scenario: Scenario) -> float:
    """Expected value per MB of freshly acquired raw data: what a freed megabyte is worth to the
    storage guard (dropping an item only pays off if it is worth less per MB than what it makes room for)."""
    value = sum(
        k.rate_per_orbit * k.base_value * (k.p_useful + (1.0 - k.p_useful) * k.junk_value_frac)
        for k in scenario.data_types
    )
    volume = sum(k.rate_per_orbit * k.raw_size_mb for k in scenario.data_types)
    return value / volume if volume > 0 else 0.0


def storage_reserve_mb(scenario: Scenario, guard_s: float, min_frac: float) -> float:
    """Free space to keep for data arriving before processing can shrink it."""
    return max(min_frac * scenario.satellite.storage_mb, inflow_rate_mb_s(scenario) * guard_s)


def storage_supply_mb(obs: Observation, wait_s: float, reserve_mb: float, pipeline_shrink_mb: float) -> float:
    """Storage headroom left for data arriving before the next pass (can be negative).

    Items already onboard keep their footprint unless processed (which frees raw minus product
    size); running jobs will free `pipeline_shrink_mb`. Future arrivals are assumed to be processed
    (compact footprint). A negative value means current items must shrink or go to make room.
    """
    sc = obs.scenario
    incoming = mean_inflow_rate_mb_s(sc) * max(wait_s, 0.0) * processed_footprint_frac(sc)
    occupied = obs.storage_used_mb - pipeline_shrink_mb
    return sc.satellite.storage_mb - reserve_mb - incoming - occupied
