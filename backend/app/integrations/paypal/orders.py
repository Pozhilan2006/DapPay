"""PayPal Orders v2 checkout operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from app.integrations.paypal.client import PayPalApiError, PayPalClient

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class CreatedOrder:
    order_id: str
    status: str
    approval_url: str


@dataclass(frozen=True)
class CapturedOrder:
    order_id: str
    capture_id: str
    status: str
    amount: Decimal
    currency: str
    create_time: datetime | None = None
    update_time: datetime | None = None


@dataclass(frozen=True)
class RetrievedCapture:
    capture_id: str
    status: str
    amount: Decimal | None
    currency: str | None
    create_time: datetime | None
    update_time: datetime | None


@dataclass(frozen=True)
class RetrievedPurchaseUnit:
    merchant_reference: str | None
    invoice_id: str | None
    amount: Decimal | None
    currency: str | None
    has_payee: bool
    captures: tuple[RetrievedCapture, ...]


@dataclass(frozen=True)
class RetrievedOrder:
    order_id: str
    status: str
    intent: str | None
    create_time: datetime | None
    update_time: datetime | None
    purchase_units: tuple[RetrievedPurchaseUnit, ...]
    payment_source_types: tuple[str, ...]
    processing_instruction: str | None


def create_order(
    *,
    amount: Decimal,
    currency: str,
    return_url: str,
    cancel_url: str,
    merchant_reference: str | None = None,
    invoice_id: str | None = None,
    client: PayPalClient | None = None,
) -> CreatedOrder:
    amount = _validate_amount(amount)
    currency = _validate_currency(currency)
    _validate_redirect_url(return_url)
    _validate_redirect_url(cancel_url)
    if not merchant_reference and not invoice_id:
        raise ValueError("A merchant reference or invoice ID is required.")
    if merchant_reference and len(merchant_reference) > 127:
        raise ValueError("Merchant reference must be 127 characters or fewer.")
    if invoice_id and len(invoice_id) > 127:
        raise ValueError("Invoice ID must be 127 characters or fewer.")

    purchase_unit: dict[str, Any] = {
        "amount": {"currency_code": currency, "value": format(amount, "f")}
    }
    if merchant_reference:
        purchase_unit["custom_id"] = merchant_reference
    if invoice_id:
        purchase_unit["invoice_id"] = invoice_id
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [purchase_unit],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }

    response = (client or PayPalClient()).post_orders_request(
        "orders", payload, str(uuid4())
    )
    if not isinstance(response, dict):
        raise PayPalApiError("PayPal returned an invalid order response.")

    order_id = response.get("id")
    status = response.get("status")
    links = response.get("links")
    if (
        not isinstance(order_id, str)
        or not _ORDER_ID_PATTERN.fullmatch(order_id)
        or not isinstance(status, str)
        or not isinstance(links, list)
    ):
        raise PayPalApiError("PayPal returned an invalid order response.")

    approval_url = next(
        (
            link.get("href")
            for link in links
            if isinstance(link, dict)
            and link.get("rel") in {"approve", "payer-action"}
        ),
        None,
    )
    if not isinstance(approval_url, str) or not _is_paypal_url(approval_url):
        raise PayPalApiError("PayPal returned an invalid approval link.")

    return CreatedOrder(
        order_id=order_id,
        status=status,
        approval_url=approval_url,
    )


def capture_order(
    order_id: str,
    *,
    client: PayPalClient | None = None,
) -> CapturedOrder:
    if not _ORDER_ID_PATTERN.fullmatch(order_id):
        raise ValueError("Invalid PayPal order ID.")

    response = (client or PayPalClient()).post_orders_request(
        f"orders/{order_id}/capture", {}, str(uuid4())
    )
    return _parse_capture_response(response, order_id)


def get_order(
    order_id: str,
    *,
    client: PayPalClient | None = None,
) -> RetrievedOrder:
    if not _ORDER_ID_PATTERN.fullmatch(order_id):
        raise ValueError("Invalid PayPal order ID.")
    response = (client or PayPalClient()).get_order_request(order_id)
    return _parse_retrieved_order(response, order_id)


def _validate_amount(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal):
        raise ValueError("Amount must be a Decimal.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be a finite positive decimal.")
    parts = amount.as_tuple()
    if len(parts.digits) > 64 or abs(parts.exponent) > 64 or amount.adjusted() > 32:
        raise ValueError("Amount exceeds the supported decimal size.")
    return amount


def _validate_currency(currency: str) -> str:
    normalized = currency.upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise ValueError("Currency must be a three-letter ISO currency code.")
    return normalized


def _validate_redirect_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Return and cancel URLs must be valid HTTP(S) URLs.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Return and cancel URLs cannot contain credentials.")


def _is_paypal_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname or ""
    return (
        parsed.scheme == "https"
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "paypal.com" or hostname.endswith(".paypal.com"))
    )


def _parse_capture_response(
    response: Any, requested_order_id: str
) -> CapturedOrder:
    if not isinstance(response, dict):
        raise PayPalApiError("PayPal returned an invalid capture response.")

    order_id = response.get("id")
    purchase_units = response.get("purchase_units")
    if (
        not isinstance(order_id, str)
        or not _ORDER_ID_PATTERN.fullmatch(order_id)
        or order_id != requested_order_id
        or not isinstance(purchase_units, list)
        or not purchase_units
    ):
        raise PayPalApiError("PayPal returned an invalid capture response.")

    payments = (
        purchase_units[0].get("payments")
        if isinstance(purchase_units[0], dict)
        else None
    )
    captures = payments.get("captures") if isinstance(payments, dict) else None
    if (
        not isinstance(captures, list)
        or not captures
        or not isinstance(captures[0], dict)
    ):
        raise PayPalApiError("PayPal returned an invalid capture response.")

    capture = captures[0]
    capture_id = capture.get("id")
    status = capture.get("status")
    amount_data = capture.get("amount")
    if (
        not isinstance(capture_id, str)
        or not capture_id
        or not isinstance(status, str)
        or not status
        or not isinstance(amount_data, dict)
        or not isinstance(amount_data.get("value"), str)
        or not isinstance(amount_data.get("currency_code"), str)
    ):
        raise PayPalApiError("PayPal returned an invalid capture response.")

    currency = amount_data["currency_code"]
    value = amount_data["value"]
    if not _CURRENCY_PATTERN.fullmatch(currency) or len(value) > 64:
        raise PayPalApiError("PayPal returned an invalid capture response.")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise PayPalApiError("PayPal returned an invalid capture response.") from None
    if (
        not amount.is_finite()
        or amount <= 0
        or len(amount.as_tuple().digits) > 64
        or abs(amount.as_tuple().exponent) > 64
        or amount.adjusted() > 32
    ):
        raise PayPalApiError("PayPal returned an invalid capture response.")

    return CapturedOrder(
        order_id=order_id,
        capture_id=capture_id,
        status=status,
        amount=amount,
        currency=currency,
        create_time=_parse_timestamp(capture.get("create_time")),
        update_time=_parse_timestamp(capture.get("update_time")),
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PayPalApiError("PayPal returned an invalid capture timestamp.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PayPalApiError("PayPal returned an invalid capture timestamp.") from None


def _parse_retrieved_order(response: Any, requested_order_id: str) -> RetrievedOrder:
    if not isinstance(response, dict):
        raise PayPalApiError("PayPal returned an invalid order response.")

    order_id = response.get("id")
    status = response.get("status")
    intent = response.get("intent")
    raw_purchase_units = response.get("purchase_units")
    if (
        order_id != requested_order_id
        or not isinstance(status, str)
        or not status
        or (intent is not None and not isinstance(intent, str))
        or not isinstance(raw_purchase_units, list)
        or not raw_purchase_units
    ):
        raise PayPalApiError("PayPal returned an invalid order response.")

    purchase_units = tuple(
        _parse_retrieved_purchase_unit(unit) for unit in raw_purchase_units
    )
    payment_source = response.get("payment_source")
    if payment_source is not None and not isinstance(payment_source, dict):
        raise PayPalApiError("PayPal returned an invalid order response.")
    payment_source_types = (
        tuple(
            source_type
            for source_type in payment_source
            if isinstance(source_type, str)
        )
        if isinstance(payment_source, dict)
        else ()
    )
    processing_instruction = response.get("processing_instruction")
    if processing_instruction is not None and not isinstance(
        processing_instruction, str
    ):
        raise PayPalApiError("PayPal returned an invalid order response.")

    return RetrievedOrder(
        order_id=order_id,
        status=status,
        intent=intent,
        create_time=_parse_timestamp(response.get("create_time")),
        update_time=_parse_timestamp(response.get("update_time")),
        purchase_units=purchase_units,
        payment_source_types=payment_source_types,
        processing_instruction=processing_instruction,
    )


def _parse_retrieved_purchase_unit(value: Any) -> RetrievedPurchaseUnit:
    if not isinstance(value, dict):
        raise PayPalApiError("PayPal returned an invalid order response.")

    custom_id = value.get("custom_id")
    invoice_id = value.get("invoice_id")
    if (
        custom_id is not None
        and not isinstance(custom_id, str)
        or invoice_id is not None
        and not isinstance(invoice_id, str)
    ):
        raise PayPalApiError("PayPal returned an invalid order response.")

    amount: Decimal | None = None
    currency: str | None = None
    amount_data = value.get("amount")
    if amount_data is not None:
        if (
            not isinstance(amount_data, dict)
            or not isinstance(amount_data.get("value"), str)
            or not isinstance(amount_data.get("currency_code"), str)
            or not _CURRENCY_PATTERN.fullmatch(amount_data["currency_code"])
            or len(amount_data["value"]) > 64
        ):
            raise PayPalApiError("PayPal returned an invalid order response.")
        try:
            amount = Decimal(amount_data["value"])
        except InvalidOperation:
            raise PayPalApiError(
                "PayPal returned an invalid order response."
            ) from None
        if not amount.is_finite() or amount < 0:
            raise PayPalApiError("PayPal returned an invalid order response.")
        currency = amount_data["currency_code"]

    payee = value.get("payee")
    if payee is not None and not isinstance(payee, dict):
        raise PayPalApiError("PayPal returned an invalid order response.")
    payee_merchant_id = payee.get("merchant_id") if isinstance(payee, dict) else None
    if payee_merchant_id is not None and not isinstance(payee_merchant_id, str):
        raise PayPalApiError("PayPal returned an invalid order response.")

    payments = value.get("payments")
    if payments is not None and not isinstance(payments, dict):
        raise PayPalApiError("PayPal returned an invalid order response.")
    raw_captures = payments.get("captures", []) if isinstance(payments, dict) else []
    if not isinstance(raw_captures, list):
        raise PayPalApiError("PayPal returned an invalid order response.")
    captures: list[RetrievedCapture] = []
    for capture in raw_captures:
        if (
            not isinstance(capture, dict)
            or not isinstance(capture.get("id"), str)
            or not capture["id"]
            or not isinstance(capture.get("status"), str)
            or not capture["status"]
        ):
            raise PayPalApiError("PayPal returned an invalid order response.")
        capture_amount: Decimal | None = None
        capture_currency: str | None = None
        capture_amount_data = capture.get("amount")
        if capture_amount_data is not None:
            if (
                not isinstance(capture_amount_data, dict)
                or not isinstance(capture_amount_data.get("value"), str)
                or not isinstance(capture_amount_data.get("currency_code"), str)
                or not _CURRENCY_PATTERN.fullmatch(
                    capture_amount_data["currency_code"]
                )
                or len(capture_amount_data["value"]) > 64
            ):
                raise PayPalApiError("PayPal returned an invalid order response.")
            try:
                capture_amount = Decimal(capture_amount_data["value"])
            except InvalidOperation:
                raise PayPalApiError(
                    "PayPal returned an invalid order response."
                ) from None
            if not capture_amount.is_finite() or capture_amount < 0:
                raise PayPalApiError("PayPal returned an invalid order response.")
            capture_currency = capture_amount_data["currency_code"]
        captures.append(
            RetrievedCapture(
                capture_id=capture["id"],
                status=capture["status"],
                amount=capture_amount,
                currency=capture_currency,
                create_time=_parse_timestamp(capture.get("create_time")),
                update_time=_parse_timestamp(capture.get("update_time")),
            )
        )

    return RetrievedPurchaseUnit(
        merchant_reference=custom_id,
        invoice_id=invoice_id,
        amount=amount,
        currency=currency,
        has_payee=payee is not None,
        captures=tuple(captures),
    )
