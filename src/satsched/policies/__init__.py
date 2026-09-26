"""Decision policies: three baselines and the value-aware engine."""

from __future__ import annotations

from typing import Callable

from satsched.policies.baselines import BandwidthRules, BentPipe, PriorityRules, ProcessAll
from satsched.policies.value_aware import ValueAwareConfig, ValueAwarePolicy

_FACTORIES: dict[str, Callable[[], object]] = {
    "bent_pipe": BentPipe,
    "process_all": ProcessAll,
    "priority_rules": PriorityRules,
    "bandwidth_rules": BandwidthRules,
    "value_aware": ValueAwarePolicy,
}
POLICY_NAMES = tuple(_FACTORIES)


def make_policy(name: str, explain: bool = False):
    if name not in _FACTORIES:
        raise KeyError(f"unknown policy '{name}', choose from {POLICY_NAMES}")
    if name == "value_aware":
        return ValueAwarePolicy(ValueAwareConfig(explain=explain))
    return _FACTORIES[name]()
