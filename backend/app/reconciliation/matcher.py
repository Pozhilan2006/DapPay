"""Deterministic matching of provisional merchant orders and PayPal captures."""

from dataclasses import dataclass
from typing import Sequence

from app.integration_contracts.payment_data import (
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
)


@dataclass(frozen=True)
class MatchedTransaction:
    merchant_order: ProvisionalMerchantOrder | None
    payments: tuple[ProvisionalPayPalPayment, ...]
    match_method: str

    @property
    def merchant_order_id(self) -> str | None:
        if self.merchant_order is not None:
            return self.merchant_order.merchant_order_id
        if self.payments:
            return self.payments[0].merchant_order_id
        return None


@dataclass(frozen=True)
class MatchResult:
    transactions: tuple[MatchedTransaction, ...]
    unmatched_payments: tuple[ProvisionalPayPalPayment, ...]


def match_records(
    orders: Sequence[ProvisionalMerchantOrder],
    payments: Sequence[ProvisionalPayPalPayment],
) -> MatchResult:
    """Match captures to orders by the shared merchant order ID.

    The provisional order DTO has no PayPal order or capture IDs, so those IDs
    cannot independently establish an order match. They remain distinct
    payment identifiers and are validated for duplicate capture records.
    Multiple capture records for an order are retained as a group.
    """
    orders_by_id: dict[str, ProvisionalMerchantOrder] = {}
    for order in orders:
        if not order.merchant_order_id.strip():
            raise ValueError("Merchant order ID cannot be empty")
        if not order.currency.strip():
            raise ValueError(
                f"Merchant order {order.merchant_order_id} has no currency code"
            )
        if not order.expected_amount.is_finite() or order.expected_amount < 0:
            raise ValueError(
                f"Merchant order {order.merchant_order_id} has an invalid amount"
            )
        if order.merchant_order_id in orders_by_id:
            raise ValueError(f"Duplicate merchant order ID: {order.merchant_order_id}")
        orders_by_id[order.merchant_order_id] = order

    capture_ids: set[str] = set()
    payments_by_order: dict[str, list[ProvisionalPayPalPayment]] = {}
    unmatched_payments: list[ProvisionalPayPalPayment] = []
    for payment in payments:
        if not payment.merchant_order_id.strip():
            raise ValueError("Payment merchant order ID cannot be empty")
        if not payment.paypal_order_id.strip():
            raise ValueError("PayPal order ID cannot be empty")
        if not payment.currency.strip():
            raise ValueError(
                f"Payment {payment.paypal_order_id} has no currency code"
            )
        if (
            not payment.actual_payment_amount.is_finite()
            or payment.actual_payment_amount < 0
        ):
            raise ValueError(
                f"Payment {payment.paypal_order_id} has an invalid amount"
            )
        if not payment.capture_status.strip():
            raise ValueError(f"Payment {payment.paypal_order_id} has no capture status")
        if payment.paypal_capture_id == "":
            raise ValueError(
                f"Payment {payment.paypal_order_id} has an empty capture ID"
            )
        if payment.paypal_capture_id:
            if payment.paypal_capture_id in capture_ids:
                raise ValueError(
                    f"Duplicate PayPal capture ID: {payment.paypal_capture_id}"
                )
            capture_ids.add(payment.paypal_capture_id)
        if payment.merchant_order_id in orders_by_id:
            payments_by_order.setdefault(payment.merchant_order_id, []).append(payment)
        else:
            unmatched_payments.append(payment)

    transactions = [
        MatchedTransaction(
            merchant_order=order,
            payments=tuple(payments_by_order.pop(order_id, [])),
            match_method="merchant_order_id",
        )
        for order_id, order in orders_by_id.items()
    ]
    transactions.extend(
        MatchedTransaction(
            merchant_order=None,
            payments=tuple(orphaned_payments),
            match_method="unmatched",
        )
        for orphaned_payments in _group_by_order_id(unmatched_payments)
    )
    return MatchResult(tuple(transactions), tuple(unmatched_payments))


def _group_by_order_id(
    payments: Sequence[ProvisionalPayPalPayment],
) -> list[list[ProvisionalPayPalPayment]]:
    grouped: dict[str, list[ProvisionalPayPalPayment]] = {}
    for payment in payments:
        grouped.setdefault(payment.merchant_order_id, []).append(payment)
    return list(grouped.values())
