"""Per-case cost from token usage and the price table."""

import math

from evalkit.cost import case_cost, has_pricing

PRICING = {
    "example-model-1": {"input": 3.00, "output": 15.00},
    "example-judge-1": {"input": 0.50, "output": 1.50},
}


def test_case_cost_hand_computed():
    # 1000 in * $3/1M + 500 out * $15/1M = 0.003 + 0.0075 = 0.0105
    cost = case_cost(PRICING, "example-model-1", 1000, 500)
    assert math.isclose(cost, 0.0105, rel_tol=0, abs_tol=1e-9)


def test_case_cost_four_decimal_value():
    cost = case_cost(PRICING, "example-model-1", 640, 120)
    assert round(cost, 4) == 0.0037


def test_missing_pricing_returns_none():
    assert case_cost(PRICING, "unknown-model", 100, 100) is None


def test_missing_usage_returns_none():
    assert case_cost(PRICING, "example-model-1", None, 100) is None
    assert case_cost(PRICING, "example-model-1", 100, None) is None


def test_has_pricing():
    assert has_pricing(PRICING, "example-model-1") is True
    assert has_pricing(PRICING, "nope") is False
