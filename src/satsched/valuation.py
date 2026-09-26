"""Value model: priority x usefulness x timeliness.

Value is realised only when data reaches the ground. Raw data additionally waits for ground
processing (`ground_delay_s`); an onboard product is immediately usable but keeps only
`retention` of the value. Processing reveals usefulness: useless items are discarded onboard.
"""

from __future__ import annotations

from satsched.config import DataType
from satsched.models import DataItem


def decay(latency_s: float, kind: DataType) -> float:
    if latency_s > kind.deadline_s:
        return 0.0
    return 0.5 ** (max(latency_s, 0.0) / kind.half_life_s)


def realized_value(item: DataItem, kind: DataType, useful: bool, delivered_s: float) -> float:
    latency = delivered_s - item.created_s
    if item.processed:
        return item.base_value * kind.retention * decay(latency, kind) if useful else 0.0
    content = 1.0 if useful else kind.junk_value_frac
    return item.base_value * content * decay(latency + kind.ground_delay_s, kind)


def expected_raw_value(item: DataItem, kind: DataType, delivered_s: float) -> float:
    content = item.p_useful + (1.0 - item.p_useful) * kind.junk_value_frac
    return item.base_value * content * decay(delivered_s - item.created_s + kind.ground_delay_s, kind)


def expected_product_value(item: DataItem, kind: DataType, delivered_s: float) -> float:
    return item.p_useful * item.base_value * kind.retention * decay(delivered_s - item.created_s, kind)


def product_value(item: DataItem, kind: DataType, delivered_s: float) -> float:
    """Value of an existing product (usefulness already confirmed by processing)."""
    return item.base_value * kind.retention * decay(delivered_s - item.created_s, kind)


def expected_product_size(item: DataItem, kind: DataType) -> float:
    return item.p_useful * kind.product_ratio * item.raw_size_mb


def ideal_value(item: DataItem, kind: DataType, useful: bool) -> float:
    """Upper bound: instant delivery, unlimited resources, full fidelity."""
    return item.base_value * (1.0 if useful else kind.junk_value_frac)
