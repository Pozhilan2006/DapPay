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
    assert "-10.00 USD" in case.explanation
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
    business_record = scenario.business_records[0].model_copy(
        update={
            "accounting_entries": [
                {
                    "paypal_refund_id": "SYNTH-PAYPAL-REFUND-001",
                    "amount": Decimal("10.00"),
                    "currency": "USD",
                }
            ]
        }
    )

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        scenario.paypal_payments,
        (business_record,),
        paypal_refund_records=(matching_paypal_refund,),
    )

    assert ExceptionType.REFUND_MISMATCH not in _types(result)
    assert ExceptionType.MISSING_ACCOUNTING_ENTRY not in _types(result)


def test_paypal_refund_without_accounting_entry_is_reported():
    result = _run("refund_discrepancy")
    case = next(
        case
        for case in result.exception_cases
        if case.exception_type == ExceptionType.MISSING_ACCOUNTING_ENTRY
    )

    assert case.capture_id == "SYNTH-CAPTURE-001"
    assert "SYNTH-PAYPAL-REFUND-001" in case.evidence_identifiers
    assert case.expected_value == {
        "refund_id": "SYNTH-PAYPAL-REFUND-001",
        "amount": Decimal("8.00"),
        "currency": "USD",
    }


def test_recent_unpaid_order_without_payment_is_not_failed_prematurely():
    scenario = SCENARIOS["missing_payment"]
    recent_order = scenario.merchant_orders[0].model_copy(
        update={
            "order_status": "pending",
            "order_created_at": SYNTHETIC_NOW - timedelta(minutes=5),
        }
    )

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (recent_order,), ()
    )

    assert result.exception_cases == ()


def test_old_pending_order_without_payment_is_missing_after_threshold():
    scenario = SCENARIOS["missing_payment"]
    old_order = scenario.merchant_orders[0].model_copy(
        update={"order_status": "pending"}
    )

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run((old_order,), ())

    assert _types(result) == {ExceptionType.MISSING_PAYMENT}


def test_pending_capture_is_not_failed_before_threshold_but_is_delayed_afterward():
    scenario = SCENARIOS["successful_payment"]
    recent_order = scenario.merchant_orders[0].model_copy(
        update={
            "order_status": "pending",
            "order_created_at": SYNTHETIC_NOW - timedelta(minutes=5),
        }
    )
    pending_payment = scenario.paypal_payments[0].model_copy(
        update={"capture_status": "PENDING"}
    )
    recent_result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (recent_order,), (pending_payment,)
    )
    old_result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (scenario.merchant_orders[0].model_copy(update={"order_status": "pending"}),),
        (pending_payment,),
    )

    assert recent_result.exception_cases == ()
    assert _types(old_result) == {ExceptionType.DELAYED_UPDATE}


def test_complete_capture_without_merchant_paid_update_waits_for_threshold():
    scenario = SCENARIOS["successful_payment"]
    recent_order = scenario.merchant_orders[0].model_copy(
        update={
            "order_status": "pending",
            "order_created_at": SYNTHETIC_NOW - timedelta(minutes=5),
        }
    )
    old_order = scenario.merchant_orders[0].model_copy(
        update={"order_status": "pending"}
    )

    recent_result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (recent_order,), scenario.paypal_payments
    )
    old_result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (old_order,), scenario.paypal_payments
    )

    assert recent_result.exception_cases == ()
    assert _types(old_result) == {ExceptionType.STATUS_MISMATCH}


def test_multiple_partial_captures_can_complete_an_unpaid_merchant_order():
    scenario = SCENARIOS["partial_captures"]
    order = scenario.merchant_orders[0].model_copy(
        update={"order_status": "pending"}
    )

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (order,), scenario.paypal_payments
    )

    status_case = next(
        case
        for case in result.exception_cases
        if case.exception_type == ExceptionType.STATUS_MISMATCH
    )
    assert status_case.expected_value == "paid"
    assert set(status_case.evidence_identifiers) >= {
        "SYNTH-CAPTURE-PART-001",
        "SYNTH-CAPTURE-PART-002",
    }


def test_denied_capture_is_missing_payment_only_after_threshold_for_unpaid_order():
    scenario = SCENARIOS["successful_payment"]
    recent_order = scenario.merchant_orders[0].model_copy(
        update={
            "order_status": "pending",
            "order_created_at": SYNTHETIC_NOW - timedelta(minutes=5),
        }
    )
    denied_payment = scenario.paypal_payments[0].model_copy(
        update={"capture_status": "DENIED"}
    )
    recent_result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (recent_order,), (denied_payment,)
    )
    old_result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (
            scenario.merchant_orders[0].model_copy(
                update={"order_status": "pending"}
            ),
        ),
        (denied_payment,),
    )

    assert recent_result.exception_cases == ()
    assert _types(old_result) == {ExceptionType.MISSING_PAYMENT}


def test_missing_payment_threshold_is_configurable():
    scenario = SCENARIOS["missing_payment"]
    pending_order = scenario.merchant_orders[0].model_copy(
        update={"order_status": "pending"}
    )

    below_threshold = ReconciliationEngine(
        clock=lambda: SYNTHETIC_NOW, delay_threshold=timedelta(hours=2)
    ).run((pending_order,), ())
    above_threshold = ReconciliationEngine(
        clock=lambda: SYNTHETIC_NOW, delay_threshold=timedelta(minutes=30)
    ).run((pending_order,), ())

    assert below_threshold.exception_cases == ()
    assert _types(above_threshold) == {ExceptionType.MISSING_PAYMENT}


def test_latest_verified_capture_event_flags_missing_merchant_update():
    scenario = SCENARIOS["out_of_order_events"]
    order = scenario.merchant_orders[0].model_copy(
        update={"order_status": "pending"}
    )
    older_pending = scenario.webhook_events[0].model_copy(
        update={
            "paypal_event_id": "SYNTH-EVENT-PENDING",
            "event_type": "PAYMENT.CAPTURE.PENDING",
            "verification_status": "SUCCESS",
            "occurred_at": SYNTHETIC_NOW - timedelta(minutes=3),
            "received_at": SYNTHETIC_NOW - timedelta(minutes=1),
        }
    )
    later_completed = scenario.webhook_events[1].model_copy(
        update={
            "paypal_event_id": "SYNTH-EVENT-COMPLETED",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "verification_status": "SUCCESS",
            "occurred_at": SYNTHETIC_NOW - timedelta(minutes=2),
            "received_at": SYNTHETIC_NOW - timedelta(minutes=4),
        }
    )

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (order,),
        scenario.paypal_payments,
        webhook_events=(later_completed, older_pending),
    )
    case = next(
        case
        for case in result.exception_cases
        if case.exception_type == ExceptionType.STATUS_MISMATCH
        and "SYNTH-EVENT-COMPLETED" in case.evidence_identifiers
    )

    assert case.expected_value == "paid"
    assert "SYNTH-EVENT-COMPLETED" in case.evidence_identifiers
    assert "SYNTH-EVENT-PENDING" not in case.evidence_identifiers


def test_distinct_webhook_event_ids_are_not_duplicate_payment_findings():
    scenario = SCENARIOS["out_of_order_events"]
    first = scenario.webhook_events[0].model_copy(
        update={
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "verification_status": "SUCCESS",
        }
    )
    second = first.model_copy(update={"paypal_event_id": "SYNTH-EVENT-OTHER"})

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        scenario.merchant_orders,
        scenario.paypal_payments,
        webhook_events=(first, second),
    )

    assert ExceptionType.DUPLICATE_WEBHOOK_DELIVERY not in _types(result)
    assert ExceptionType.STATUS_MISMATCH not in _types(result)


def test_unverified_capture_events_do_not_drive_merchant_status_reconciliation():
    scenario = SCENARIOS["out_of_order_events"]
    order = scenario.merchant_orders[0].model_copy(
        update={
            "order_status": "pending",
            "order_created_at": SYNTHETIC_NOW - timedelta(minutes=5),
        }
    )
    unverified_event = scenario.webhook_events[0].model_copy(
        update={
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "verification_status": "synthetic_unverified",
        }
    )

    result = ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
        (order,),
        scenario.paypal_payments,
        webhook_events=(unverified_event,),
    )

    assert ExceptionType.STATUS_MISMATCH not in _types(result)


def test_refund_requires_explicit_capture_link_when_order_has_multiple_captures():
    partial = SCENARIOS["partial_captures"]
    refund_order = SCENARIOS["refund_discrepancy"]
    refund_without_capture_id = {
        "merchant_order_id": "SYNTH-MERCHANT-ORDER-001",
        "amount": Decimal("8.00"),
        "currency": "USD",
    }

    with pytest.raises(ValueError, match="explicit capture ID"):
        ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
            partial.merchant_orders,
            partial.paypal_payments,
            refund_order.business_records,
            paypal_refund_records=(refund_without_capture_id,),
        )


def test_refund_capture_id_must_resolve_to_a_known_original_capture():
    scenario = SCENARIOS["refund_discrepancy"]
    unlinked_refund = {
        **scenario.paypal_refund_records[0],
        "capture_id": "SYNTH-UNKNOWN-CAPTURE",
    }

    with pytest.raises(ValueError, match="known original capture"):
        ReconciliationEngine(clock=lambda: SYNTHETIC_NOW).run(
            scenario.merchant_orders,
            scenario.paypal_payments,
            scenario.business_records,
            paypal_refund_records=(unlinked_refund,),
        )


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
