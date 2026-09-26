import pytest

from satsched.config import DataType, Processor
from satsched.models import DataItem
from satsched.valuation import (
    decay,
    expected_product_size,
    expected_product_value,
    expected_raw_value,
    ideal_value,
    realized_value,
)

KIND = DataType(
    name="img",
    raw_size_mb=100.0,
    base_value=10.0,
    half_life_s=1000.0,
    deadline_s=5000.0,
    rate_per_orbit=1.0,
    sunlit_only=False,
    p_useful=0.5,
    junk_value_frac=0.1,
    processor=Processor.GPU,
    proc_time_s=60.0,
    mem_mb=100.0,
    product_ratio=0.1,
    retention=0.8,
    ground_delay_s=500.0,
)


def item(**overrides):
    base = dict(id=1, kind="img", created_s=0.0, raw_size_mb=100.0, base_value=10.0, p_useful=0.5, size_mb=100.0)
    base.update(overrides)
    return DataItem(**base)


def test_decay_half_life_and_deadline():
    assert decay(0, KIND) == 1.0
    assert decay(1000, KIND) == pytest.approx(0.5)
    assert decay(5000, KIND) == pytest.approx(0.5**5)
    assert decay(5001, KIND) == 0.0
    assert decay(-10, KIND) == 1.0


def test_raw_useful_value_includes_ground_delay():
    v = realized_value(item(), KIND, useful=True, delivered_s=500.0)
    assert v == pytest.approx(10.0 * 0.5)


def test_raw_junk_value_is_fraction():
    v = realized_value(item(), KIND, useful=False, delivered_s=500.0)
    assert v == pytest.approx(10.0 * 0.1 * 0.5)


def test_product_value_uses_retention_without_ground_delay():
    v = realized_value(item(processed=True), KIND, useful=True, delivered_s=1000.0)
    assert v == pytest.approx(10.0 * 0.8 * 0.5)


def test_expected_values_weight_usefulness():
    raw = expected_raw_value(item(), KIND, delivered_s=500.0)
    assert raw == pytest.approx(10.0 * (0.5 + 0.5 * 0.1) * 0.5)
    prod = expected_product_value(item(), KIND, delivered_s=1000.0)
    assert prod == pytest.approx(0.5 * 10.0 * 0.8 * 0.5)


def test_expected_product_size():
    assert expected_product_size(item(), KIND) == pytest.approx(0.5 * 0.1 * 100.0)


def test_ideal_value():
    assert ideal_value(item(), KIND, useful=True) == 10.0
    assert ideal_value(item(), KIND, useful=False) == pytest.approx(1.0)
