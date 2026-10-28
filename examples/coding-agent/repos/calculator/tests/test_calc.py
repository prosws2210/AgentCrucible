import pytest
from calc import apply_discount, total


def test_apply_discount():
    assert apply_discount(100, 20) == 80.0
    assert apply_discount(59.99, 0) == 59.99


def test_apply_discount_rejects_bad_percent():
    with pytest.raises(ValueError):
        apply_discount(10, 120)


def test_total():
    assert total([1.10, 2.20]) == 3.3
