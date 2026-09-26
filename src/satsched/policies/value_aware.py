"""Value-aware decision engine: 'process now, store, transmit or drop?' for every onboard item.

Each step (receding horizon):
  1. Value each item's options (raw downlink vs onboard processing) from predicted delivery times.
  2. Price the scarce resources over the planning horizon (next K contact windows) by dual
     decomposition (see pricing.py): downlink MB, energy Wh, GPU-s, CPU-s and storage MB.
     A second pass re-estimates each raw item's delivery time from its place in the downlink
     queue and re-solves the prices.
  3. Each item takes its best net-utility option: PROCESS / RAW / NONE.
  4. Processing admission: start the best PROCESS items now if a slot, RAM and the battery
     headroom (reserve through the next eclipse) allow; the others are STORED for later processing.
  5. Downlink order: value density plus an urgency term (value lost by waiting for the next pass).
  6. Storage guard: keep free space for incoming data by dropping the lowest value-density items;
     worthless items (decayed, no pass before the deadline) are dropped at once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from satsched.config import DataType, Processor
from satsched.models import DataItem, Explanation, Observation, Plan, Route, Stage
from satsched.policies.pricing import (
    BLOCKED,
    arrival_value_density,
    NONE,
    PROCESS,
    RAW,
    SATURATED_PRICE,
    OptionBook,
    choose,
    downlink_supply_mb,
    energy_budget_wh,
    energy_headroom_wh,
    horizon_end_s,
    solve_prices,
    storage_reserve_mb,
    storage_supply_mb,
)
from satsched.simulator.resources import free_ram_mb, free_slots
from satsched.valuation import expected_product_size, expected_product_value, expected_raw_value, product_value

BW, ENERGY, GPU, CPU, STORAGE = range(5)


@dataclass(frozen=True)
class ValueAwareConfig:
    horizon_windows: int = 2  # contact windows included in the planning horizon (tuned on seeds 1000-1003)
    storage_guard_s: float = 300.0  # keep room for this much peak acquisition
    min_reserve_frac: float = 0.05  # ... and never less than this fraction of storage
    urgency_weight: float = 1.0  # weight of 'value lost if we wait for the next pass'
    worthless_frac: float = 0.001  # drop items expected to deliver < 0.1% of their base value
    explain: bool = False  # attach a human-readable reason to every decision
    # ablation switches (all True = full engine)
    use_prices: bool = True  # solve shadow prices (False: every price is zero)
    price_storage: bool = True  # include storage as a priced resource
    queue_aware: bool = True  # second pass re-valuing raw items at their queue position
    battery_guard: bool = True  # keep the battery reserve through the next eclipse when admitting jobs


@dataclass(frozen=True)
class _Context:
    obs: Observation
    cfg: ValueAwareConfig
    t: float
    t_next: float  # start of the next downlink opportunity (t when in contact), inf if none
    t_after: float  # start of the opportunity after that one
    rate: float
    horizon_s: float
    horizon_windows: int
    in_contact: bool
    committed_wh: float  # energy still needed by running jobs
    running_s: dict[Processor, float]
    pipeline_shrink_mb: float  # storage that running jobs are expected to free
    reserve_mb: float  # free space kept for incoming data
    product_ready: dict[str, float]  # delivery time of a product if its processing starts now


@dataclass(frozen=True, slots=True)
class _Row:
    item: DataItem
    kind: DataType
    ev_raw: float
    ev_proc: float
    size_raw: float
    size_proc: float
    energy_proc: float
    proc_s: float


def _context(obs: Observation, cfg: ValueAwareConfig) -> _Context:
    sched, t, sat, types = obs.schedule, obs.time_s, obs.scenario.satellite, obs.types
    nxt = sched.next_window(t)
    after = sched.next_window(nxt.end_s) if nxt else None
    running = [i for i in obs.items if i.stage is Stage.PROCESSING]
    running_s = {Processor.CPU: 0.0, Processor.GPU: 0.0}
    for it in running:
        running_s[types[it.kind].processor] += it.proc_remaining_s
    committed = sum(sat.power_w(types[i.kind].processor) * i.proc_remaining_s / 3600.0 for i in running)
    ready: dict[str, float] = {}
    for kind in types.values():
        if kind.processable:
            done = t + kind.proc_time_s
            win = sched.next_window(done)
            ready[kind.name] = max(win.start_s, done) if win else math.inf
    return _Context(
        obs=obs,
        cfg=cfg,
        t=t,
        t_next=max(t, nxt.start_s) if nxt else math.inf,
        t_after=after.start_s if after else math.inf,
        rate=nxt.rate_mb_s if nxt else 1.0,
        horizon_s=max(horizon_end_s(sched, t, cfg.horizon_windows) - t, 0.0),
        horizon_windows=cfg.horizon_windows,
        in_contact=sched.capacity_between(t, t + obs.dt_s) > 0,
        committed_wh=committed,
        running_s=running_s,
        pipeline_shrink_mb=sum(i.size_mb - expected_product_size(i, types[i.kind]) for i in running),
        reserve_mb=storage_reserve_mb(obs.scenario, cfg.storage_guard_s, cfg.min_reserve_frac),
        product_ready=ready,
    )


def _assess(item: DataItem, ctx: _Context) -> _Row:
    kind = ctx.obs.types[item.kind]
    arrival = ctx.t_next + item.remaining_mb / ctx.rate
    if item.stage is Stage.PRODUCT:
        ev_raw = product_value(item, kind, arrival)
    else:
        ev_raw = expected_raw_value(item, kind, arrival)
    if item.stage is Stage.RAW and kind.processable and item.sent_mb == 0:
        power = ctx.obs.scenario.satellite.power_w(kind.processor)
        return _Row(
            item, kind, ev_raw, expected_product_value(item, kind, ctx.product_ready[kind.name]),
            item.remaining_mb, expected_product_size(item, kind), power * kind.proc_time_s / 3600.0, kind.proc_time_s,
        )
    return _Row(item, kind, ev_raw, BLOCKED, item.remaining_mb, 0.0, 0.0, 0.0)


def _book(rows: list[_Row], ctx: _Context, worthless: np.ndarray) -> OptionBook:
    n = len(rows)
    sat = ctx.obs.scenario.satellite
    tx_wh_per_mb = sat.radio_w / ctx.rate / 3600.0
    values = np.array([[r.ev_raw for r in rows], [r.ev_proc for r in rows]])
    values[:, worthless] = BLOCKED
    uses = np.zeros((2, 5, n))
    for k, r in enumerate(rows):
        uses[RAW, BW, k] = r.size_raw
        uses[RAW, ENERGY, k] = r.size_raw * tx_wh_per_mb
        # storage is priced by net change: keeping an item (RAW or NONE) adds nothing to what it already
        # occupies, processing frees raw minus product size (a negative use)
        if r.ev_proc > BLOCKED:
            uses[PROCESS, BW, k] = r.size_proc
            uses[PROCESS, ENERGY, k] = r.energy_proc + r.size_proc * tx_wh_per_mb
            uses[PROCESS, GPU if r.kind.processor is Processor.GPU else CPU, k] = r.proc_s
            uses[PROCESS, STORAGE, k] = r.size_proc - r.size_raw
    wait_s = min(ctx.t_next - ctx.t, ctx.horizon_s) if math.isfinite(ctx.t_next) else ctx.horizon_s
    supply = np.array([
        downlink_supply_mb(ctx.obs.schedule, ctx.t, ctx.horizon_windows),
        energy_budget_wh(ctx.obs, ctx.horizon_s, ctx.committed_wh),
        sat.gpu_slots * ctx.horizon_s - ctx.running_s[Processor.GPU],
        sat.cpu_cores * ctx.horizon_s - ctx.running_s[Processor.CPU],
        storage_supply_mb(ctx.obs, wait_s, ctx.reserve_mb, ctx.pipeline_shrink_mb) if ctx.cfg.price_storage else math.inf,
    ])
    return OptionBook(values=values, uses=uses, supply=supply)


def _solve(rows: list[_Row], ctx: _Context, worthless: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    book = _book(rows, ctx, worthless)
    prices = solve_prices(book) if ctx.cfg.use_prices else np.zeros(book.supply.shape[0])
    choice, u = choose(book, prices)
    return choice, u, prices


def _queue_aware(rows: list[_Row], choice: np.ndarray, ctx: _Context) -> list[_Row]:
    """Re-value raw transmissions at their queue position instead of 'start of the next pass'."""
    queued = [k for k in range(len(rows)) if choice[k] == RAW]
    queued.sort(key=lambda k: rows[k].ev_raw / max(rows[k].size_raw, 1e-6), reverse=True)
    updated = list(rows)
    volume = 0.0
    for k in queued:
        volume += rows[k].size_raw
        arrival = ctx.obs.schedule.time_to_send(ctx.t, volume)
        updated[k] = replace(rows[k], ev_raw=_later_value(rows[k].item, rows[k].kind, arrival))
    return updated


def _admit(rows: list[_Row], choice: np.ndarray, u: np.ndarray, ctx: _Context) -> tuple[list[int], dict[int, str]]:
    obs = ctx.obs
    candidates = [k for k in range(len(rows)) if choice[k] == PROCESS]
    gain = {k: u[PROCESS, k] - max(u[RAW, k], 0.0) for k in candidates}
    candidates.sort(key=lambda k: gain[k] / max(rows[k].proc_s, 1.0), reverse=True)
    slots = free_slots(obs.items, obs.scenario)
    ram = free_ram_mb(obs.items, obs.scenario)
    headroom = energy_headroom_wh(obs, ctx.committed_wh) if ctx.cfg.battery_guard else math.inf
    admitted: list[int] = []
    waiting: dict[int, str] = {}
    for k in candidates:
        r = rows[k]
        if slots[r.kind.processor] <= 0:
            waiting[r.item.id] = f"{r.kind.processor.value.upper()} busy"
        elif r.kind.mem_mb > ram:
            waiting[r.item.id] = "not enough free RAM"
        elif r.energy_proc > headroom:
            waiting[r.item.id] = "battery must stay above reserve through the next eclipse"
        else:
            admitted.append(r.item.id)
            slots[r.kind.processor] -= 1
            ram -= r.kind.mem_mb
            headroom -= r.energy_proc
    return admitted, waiting


def _later_value(item: DataItem, kind: DataType, t: float) -> float:
    if item.stage is Stage.PRODUCT:
        return product_value(item, kind, t)
    return expected_raw_value(item, kind, t)


def _downlink(rows: list[_Row], choice: np.ndarray, ctx: _Context, cfg: ValueAwareConfig) -> list[int]:
    if not ctx.in_contact:
        return []
    keyed = []
    for k, r in enumerate(rows):
        if choice[k] != RAW:
            continue
        size = max(r.item.remaining_mb, 1e-6)
        later = _later_value(r.item, r.kind, ctx.t_after + size / ctx.rate)
        urgency = max(r.ev_raw - later, 0.0)
        keyed.append(((r.ev_raw + cfg.urgency_weight * urgency) / size, r.item.id))
    keyed.sort(key=lambda x: (-x[0], x[1]))
    return [item_id for _, item_id in keyed]


def _drops(
    rows: list[_Row], u: np.ndarray, worthless: np.ndarray, admitted: set[int], ctx: _Context, cfg: ValueAwareConfig
) -> tuple[list[int], list[int]]:
    obs = ctx.obs
    capacity = obs.scenario.satellite.storage_mb
    dropped_worthless = [rows[k].item.id for k in np.flatnonzero(worthless)]
    free = capacity - obs.storage_used_mb + sum(rows[k].item.size_mb for k in np.flatnonzero(worthless))
    reserve = ctx.reserve_mb
    guard: list[int] = []
    if free >= reserve:
        return dropped_worthless, guard
    # Only items worth less per MB than the data they make room for are worth dropping, cheapest first.
    threshold = arrival_value_density(obs.scenario)

    def density(k: int) -> float:
        return max(rows[k].ev_raw, rows[k].ev_proc, 0.0) / max(rows[k].item.size_mb, 1e-6)

    candidates = [
        k for k, r in enumerate(rows)
        if not worthless[k] and r.item.stage in (Stage.RAW, Stage.PRODUCT) and r.item.sent_mb == 0
        and r.item.id not in admitted and density(k) < threshold
    ]
    candidates.sort(key=lambda k: (density(k), rows[k].item.id))
    for k in candidates:
        if free >= reserve:
            break
        guard.append(rows[k].item.id)
        free += rows[k].item.size_mb
    return dropped_worthless, guard


def _fmt(x: float) -> str:
    if x <= BLOCKED / 2:
        return "n/a"
    return "very high (frees scarce storage)" if x >= SATURATED_PRICE else f"{x:.2f}"


def _fmt_price(x: float, unit: str, digits: int) -> str:
    return "saturated" if x >= SATURATED_PRICE else f"{x:.{digits}f}/{unit}"


def _explain(
    rows: list[_Row], choice: np.ndarray, u: np.ndarray, prices: np.ndarray, admitted: set[int],
    waiting: dict[int, str], worthless_ids: set[int], guard_ids: set[int],
) -> dict[int, Explanation]:
    price_txt = (
        f"[downlink {_fmt_price(prices[BW], 'MB', 4)}, energy {_fmt_price(prices[ENERGY], 'Wh', 3)}, "
        f"GPU {_fmt_price(prices[GPU], 's', 4)}, storage {_fmt_price(prices[STORAGE], 'MB', 4)}]"
    )
    out: dict[int, Explanation] = {}
    for k, r in enumerate(rows):
        i = r.item.id
        up, ur = u[PROCESS, k], u[RAW, k]
        if i in worthless_ids:
            route, why = Route.DROP, "drop: no pass before its value decays away"
        elif i in guard_ids:
            route, why = Route.DROP, "drop: storage guard, lowest value per MB onboard"
        elif i in admitted:
            route = Route.PROCESS_NOW
            why = f"process now: U_proc {_fmt(up)} > U_raw {_fmt(ur)}; ~{r.size_proc:.0f} MB product vs {r.size_raw:.0f} MB raw"
        elif choice[k] == PROCESS:
            route, why = Route.STORE, f"store for later processing ({waiting.get(i, 'queued')}); U_proc {_fmt(up)}"
        elif choice[k] == RAW:
            what = "product" if r.item.stage is Stage.PRODUCT else "raw"
            route, why = Route.TRANSMIT, f"transmit {what}: U_raw {_fmt(ur)} >= U_proc {_fmt(up)}"
        else:
            route, why = Route.STORE, "store: no option pays for its resources within the horizon"
        out[i] = Explanation(route, up, ur, r.ev_proc, r.ev_raw, float(prices[BW]), float(prices[ENERGY]),
                             f"{why} {price_txt}")
    return out


class ValueAwarePolicy:
    name = "value_aware"

    def __init__(self, config: ValueAwareConfig | None = None) -> None:
        self.config = config or ValueAwareConfig()

    def decide(self, obs: Observation) -> Plan:
        cfg = self.config
        ctx = _context(obs, cfg)
        rows = [_assess(it, ctx) for it in obs.items if it.stage in (Stage.RAW, Stage.PRODUCT)]
        if not rows:
            return Plan()
        worthless = np.array([max(r.ev_raw, r.ev_proc) < cfg.worthless_frac * r.item.base_value for r in rows])
        choice, u, prices = _solve(rows, ctx, worthless)
        if cfg.queue_aware:
            rows = _queue_aware(rows, choice, ctx)
            choice, u, prices = _solve(rows, ctx, worthless)
        admitted, waiting = _admit(rows, choice, u, ctx)
        admitted_set = set(admitted)
        worthless_ids, guard_ids = _drops(rows, u, worthless, admitted_set, ctx, cfg)
        drop_set = set(worthless_ids) | set(guard_ids)
        downlink = [i for i in _downlink(rows, choice, ctx, cfg) if i not in drop_set]
        explanations = (
            _explain(rows, choice, u, prices, admitted_set, waiting, set(worthless_ids), set(guard_ids))
            if cfg.explain else {}
        )
        return Plan(
            process=tuple(admitted),
            downlink=tuple(downlink),
            drop=tuple(worthless_ids + guard_ids),
            explanations=explanations,
        )
