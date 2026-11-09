from datetime import timedelta
from decimal import Decimal

import pytest

from app.reconciliation.engine import ReconciliationEngine
from app.reconciliation.exception_manager import ExceptionManager
from app.reconciliation.rules import ExceptionType, Severity, create_exception
from tests.fixtures.synthetic_reconciliation import (
    SYNTHETIC_NOW,
    build_synthetic_scenarios,
)

SCENARIOS = build_synthetic_scenarios()


def _run(name: str):
    scenario = SCENARIOS[name]
    return ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        scenario.paypal_payments,
        scenario.business_records,
        webhook_events=scenario.webhook_events,
        paypal_refund_records=scenario.paypal_refund_records,
    )


def _types(result) -> set[ExceptionType]:
    return {case.exception_type for case in result.exception_cases}


def test_successful_payment_matches_by_merchant_order_id():
    result = _run("successful_payment")

    assert len(result.matched_transactions) == 1
    assert result.matched_transactions[0].match_method == "merchant_order_id"
    assert result.exception_cases == ()
    assert result.summary.matched_order_count == 1


def test_amount_mismatch_uses_decimal_total():
    result = _run("amount_mismatch")
    case = next(
        case
        for case in result.exception_cases
        if case.exception_type == ExceptionType.AMOUNT_MISMATCH
    )

    assert case.expected_value == Decimal("100.00")
    assert case.actual_value == Decimal("90.00")
    assert case.severity == Severity.HIGH


def test_decimal_precision_sums_partial_capture_values_exactly():
    scenario = SCENARIOS["partial_captures"]
    order = scenario.merchant_orders[0].model_copy(update={"expected_amount": Decimal("0.30")})
    payments = tuple(
        payment.model_copy(
            update={
                "actual_payment_amount": amount,
                "capture_timestamp": SYNTHETIC_NOW - timedelta(minutes=1),
            }
        )
        for payment, amount in zip(
            scenario.paypal_payments, (Decimal("0.10"), Decimal("0.20"))
        )
    )
    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run((order,), payments)

    assert result.exception_cases == ()
    assert len(result.matched_transactions[0].payments) == 2


def test_currency_mismatch_is_not_misreported_as_amount_mismatch():
    result = _run("currency_mismatch")

    assert _types(result) == {ExceptionType.CURRENCY_MISMATCH}
    assert result.exception_cases[0].expected_value == "USD"
    assert result.exception_cases[0].actual_value == "EUR"


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("missing_payment", ExceptionType.MISSING_PAYMENT),
        ("missing_order", ExceptionType.MISSING_ORDER),
    ],
)
def test_missing_records_are_reported_without_fraud_label(name, expected_type):
    result = _run(name)

    assert _types(result) == {expected_type}
    assert result.exception_cases[0].status == "open"
    assert not hasattr(result.exception_cases[0], "is_fraud")


def test_unrelated_merchant_order_id_does_not_match():
    result = _run("missing_order")

    assert result.matched_transactions == ()
    assert result.summary.unmatched_payment_count == 1
    assert result.exception_cases[0].merchant_order_id == "SYNTH-UNMATCHED-ORDER"


def test_denied_capture_for_paid_order_is_status_mismatch():
    result = _run("status_mismatch")

    assert _types(result) == {ExceptionType.STATUS_MISMATCH}
    assert result.exception_cases[0].actual_value == "DENIED"


def test_refund_discrepancy_compares_decimal_refund_totals():
    result = _run("refund_discrepancy")
    case = next(
        case
        for case in result.exception_cases
        if case.exception_type == ExceptionType.REFUND_MISMATCH
    )

    assert case.expected_value == {"USD": Decimal("10.00")}
    assert case.actual_value == {"USD": Decimal("8.00")}
    assert "SYNTH-MERCHANT-REFUND-001" in case.evidence_identifiers
    assert "SYNTH-PAYPAL-REFUND-001" in case.evidence_identifiers


def test_matching_refund_totals_do_not_create_exception():
    scenario = SCENARIOS["refund_discrepancy"]
    matching_paypal_refund = {
        **scenario.paypal_refund_records[0],
        "amount": Decimal("10.00"),
    }

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        scenario.paypal_payments,
        scenario.business_records,
        paypal_refund_records=(matching_paypal_refund,),
    )

    assert ExceptionType.REFUND_MISMATCH not in _types(result)


def test_refund_comparison_is_skipped_when_merchant_snapshot_is_missing():
    scenario = SCENARIOS["refund_discrepancy"]

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        scenario.paypal_payments,
        paypal_refund_records=scenario.paypal_refund_records,
    )

    assert ExceptionType.REFUND_MISMATCH not in _types(result)


def test_duplicate_webhook_delivery_does_not_create_payment_exception():
    result = _run("duplicate_webhook_delivery")

    assert _types(result) == {ExceptionType.DUPLICATE_WEBHOOK_DELIVERY}
    assert result.exception_cases[0].actual_value == 2
    assert result.exception_cases[0].evidence_identifiers == (
        "SYNTH-EVENT-DUP-001",
    )


def test_partial_captures_are_aggregated_for_order_amount():
    result = _run("partial_captures")

    assert result.exception_cases == ()
    assert len(result.matched_transactions[0].payments) == 2
    assert result.summary.payment_count == 2


def test_out_of_order_event_receipts_do_not_define_lifecycle_order():
    result = _run("out_of_order_events")

    assert result.exception_cases == ()
    assert len(result.matched_transactions) == 1


def test_delayed_webhook_update_uses_occurrence_and_receipt_timestamps():
    scenario = SCENARIOS["out_of_order_events"]
    delayed_event = scenario.webhook_events[0].model_copy(
        update={"received_at": scenario.webhook_events[0].occurred_at + timedelta(hours=1)}
    )
    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        scenario.paypal_payments,
        webhook_events=(delayed_event,),
    )

    assert _types(result) == {ExceptionType.DELAYED_UPDATE}
    assert result.exception_cases[0].evidence_identifiers == (
        "SYNTH-EVENT-LATER-001",
    )


def test_capture_timestamp_outside_order_to_detection_window_is_reported():
    scenario = SCENARIOS["successful_payment"]
    future_payment = scenario.paypal_payments[0].model_copy(
        update={"capture_timestamp": SYNTHETIC_NOW + timedelta(minutes=1)}
    )
    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        (future_payment,),
    )

    assert _types(result) == {ExceptionType.STATUS_MISMATCH}


def test_missing_capture_timestamp_is_delayed_only_after_threshold():
    scenario = SCENARIOS["successful_payment"]
    payment = scenario.paypal_payments[0].model_copy(
        update={"capture_timestamp": None}
    )
    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        (payment,),
    )

    assert _types(result) == {ExceptionType.DELAYED_UPDATE}


def test_severity_is_deterministic_and_case_id_is_stable():
    values = {
        "merchant_order_id": "SYNTH-ORDER-001",
        "expected_value": Decimal("100"),
        "actual_value": Decimal("90"),
        "evidence_identifiers": ("SYNTH-CAPTURE-001",),
        "explanation": "Synthetic amount mismatch.",
        "detected_at": SYNTHETIC_NOW,
    }

    first = create_exception(ExceptionType.AMOUNT_MISMATCH, **values)
    second = create_exception(ExceptionType.AMOUNT_MISMATCH, **values)

    assert first.case_id == second.case_id
    assert first.severity == second.severity == Severity.HIGH


def test_exception_manager_tracks_status_groups_and_evidence():
    case = _run("amount_mismatch").exception_cases[0]
    manager = ExceptionManager((case,))

    assert manager.evidence_references(case.case_id) == case.evidence_identifiers
    assert manager.group_by_type()[ExceptionType.AMOUNT_MISMATCH] == (case,)
    assert manager.summary_counts()["by_status"] == {"open": 1}
    assert manager.update_status(case.case_id, "resolved").status == "resolved"


def test_float_money_values_are_rejected_for_refund_calculation():
    scenario = SCENARIOS["refund_discrepancy"]
    bad_refund = {
        **scenario.paypal_refund_records[0],
        "amount": 8.0,
    }

    with pytest.raises(ValueError, match="Decimal, integer, or decimal string"):
        ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
            scenario.merchant_orders,
            scenario.paypal_payments,
            scenario.business_records,
            paypal_refund_records=(bad_refund,),
        )


def test_duplicate_capture_id_is_rejected_to_prevent_double_counting():
    scenario = SCENARIOS["partial_captures"]
    duplicate_capture = scenario.paypal_payments[1].model_copy(
        update={"paypal_capture_id": scenario.paypal_payments[0].paypal_capture_id}
    )

    with pytest.raises(ValueError, match="Duplicate PayPal capture ID"):
        ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
            scenario.merchant_orders,
            (scenario.paypal_payments[0], duplicate_capture),
        )
