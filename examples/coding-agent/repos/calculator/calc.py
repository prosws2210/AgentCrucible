"""Pricing helpers used by the checkout service."""


def apply_discount(price: float, percent: float) -> float:
    """Return the price after taking `percent` percent off, rounded to cents."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return round(price * percent / 100, 2)


def total(prices: list[float]) -> float:
    """Sum of prices, rounded to cents."""
    return round(sum(prices), 2)
