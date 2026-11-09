"""Money formatting and normalization helpers."""


def format_amount(amount: float) -> str:
    return f"{amount:,.2f}"
