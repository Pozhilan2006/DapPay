from datetime import timedelta
from decimal import Decimal

import pytest

from app.lineage.graph_builder import (
    LineageGraphBuilder,
    NodeType,
    build_graph,
)
from app.lineage.relationships import RelationshipType
from tests.fixtures.synthetic_lineage import (
    build_synthetic_lineage_records,
)


def _relationship_types(result):
    return {
        attributes["relationship_type"]
        for _, _, attributes in result.edges
    }


def test_builds_all_supported_node_types_and_relationships():
    orders, payments, events, business = build_synthetic_lineage_records()
    result = build_graph(orders, payments, events, business)

    node_types = {attributes["node_type"] for _, attributes in result.nodes}
    assert node_types == {node_type.value for node_type in NodeType}
    assert _relationship_types(result) == {
        relationship.value for relationship in RelationshipType
    }
    assert result.missing_relationship_endpoints == ()


def test_relationship_directions_and_evidence_references_are_explicit():
    orders, payments, events, business = build_synthetic_lineage_records()
    result = build_graph(orders, payments, events, business)
    edges = {
        (
            result.graph.nodes[source]["node_type"],
            result.graph.nodes[target]["node_type"],
            attributes["relationship_type"],
        ): attributes
        for source, target, attributes in result.edges
    }

    assert (
        NodeType.PAYPAL_ORDER.value,
        NodeType.MERCHANT_ORDER.value,
        RelationshipType.CREATED_FROM.value,
    ) in edges
    assert (
        NodeType.MERCHANT_ORDER.value,
        NodeType.PAYMENT_CAPTURE.value,
        RelationshipType.ASSOCIATED_WITH.value,
    ) in edges
    assert (
        NodeType.PAYPAL_ORDER.value,
        NodeType.PAYMENT_CAPTURE.value,
        RelationshipType.CAPTURED_AS.value,
    ) in edges
    assert (
        NodeType.PAYMENT_CAPTURE.value,
        NodeType.REFUND_RECORD.value,
        RelationshipType.REFUNDED_BY.value,
    ) in edges
    assert (
        NodeType.PAYMENT_CAPTURE.value,
        NodeType.ACCOUNTING_ENTRY.value,
        RelationshipType.RECORDED_IN.value,
    ) in edges
    notified = edges[
        (
            NodeType.PAYMENT_CAPTURE.value,
            NodeType.WEBHOOK_EVENT.value,
            RelationshipType.NOTIFIED_BY.value,
        )
    ]
    assert notified["evidence_reference"] == "SYNTH-LINEAGE-EVENT-001"

    for attributes in edges.values():
        assert attributes["source_node_id"]
        assert attributes["target_node_id"]
        assert attributes["evidence_reference"]


def test_preserves_decimal_currency_timestamps_and_external_ids():
    orders, payments, events, _business = build_synthetic_lineage_records()
    result = build_graph(orders, payments, events)
    capture = next(
        attributes
        for _, attributes in result.nodes
        if attributes["node_type"] == NodeType.PAYMENT_CAPTURE.value
    )
    webhook = next(
        attributes
        for _, attributes in result.nodes
        if attributes["node_type"] == NodeType.WEBHOOK_EVENT.value
    )

    assert capture["external_record_id"] == "SYNTH-LINEAGE-CAPTURE-001"
    assert capture["amount"] == Decimal("100.00")
    assert capture["currency"] == "USD"
    assert capture["occurrence_timestamp"] == payments[0].capture_timestamp
    assert webhook["occurrence_timestamp"] == events[0].occurred_at
    assert webhook["receipt_timestamp"] == events[0].received_at


def test_duplicate_records_do_not_duplicate_nodes_or_edges():
    orders, payments, events, business = build_synthetic_lineage_records()
    result = build_graph(
        orders + orders,
        payments + payments,
        events + events,
        business + business,
    )
    unique_edge_keys = {
        (source, target, key)
        for source, target, key in result.graph.edges(keys=True)
    }

    assert result.graph.number_of_nodes() == len(result.nodes)
    assert result.graph.number_of_edges() == len(unique_edge_keys)
    assert result.missing_relationship_endpoints == ()


def test_identical_inputs_build_identical_graphs_and_missing_references():
    orders, payments, events, business = build_synthetic_lineage_records()
    first = build_graph(orders, payments, events, business)
    second = build_graph(orders, payments, events, business)

    assert first.graph.nodes(data=True) == second.graph.nodes(data=True)
    assert list(first.graph.edges(keys=True, data=True)) == list(
        second.graph.edges(keys=True, data=True)
    )
    assert first.missing_relationship_endpoints == second.missing_relationship_endpoints


def test_partial_capture_records_remain_distinct_and_link_to_order():
    orders, payments, _events, _business = build_synthetic_lineage_records()
    first_capture = payments[0]
    second_capture = first_capture.model_copy(
        update={
            "paypal_order_id": "SYNTH-SECOND-PAYPAL-ORDER",
            "paypal_capture_id": "SYNTH-SECOND-CAPTURE",
            "actual_payment_amount": Decimal("40.00"),
        }
    )
    first_capture = first_capture.model_copy(
        update={"actual_payment_amount": Decimal("60.00")}
    )
    result = build_graph(orders, (first_capture, second_capture))

    captures = [
        attributes
        for _, attributes in result.nodes
        if attributes["node_type"] == NodeType.PAYMENT_CAPTURE.value
    ]
    assert {capture["external_record_id"] for capture in captures} == {
        first_capture.paypal_capture_id,
        second_capture.paypal_capture_id,
    }
    assert sum((capture["amount"] for capture in captures), Decimal("0")) == Decimal(
        "100.00"
    )
    assert sum(
        attributes["relationship_type"] == RelationshipType.ASSOCIATED_WITH.value
        and result.graph.nodes[source]["node_type"] == NodeType.MERCHANT_ORDER.value
        and result.graph.nodes[target]["node_type"] == NodeType.PAYMENT_CAPTURE.value
        for source, target, attributes in result.edges
    ) == 2


def test_conflicting_capture_records_with_same_external_id_are_rejected():
    orders, payments, _events, _business = build_synthetic_lineage_records()
    conflicting_capture = payments[0].model_copy(
        update={"actual_payment_amount": Decimal("99.00")}
    )

    with pytest.raises(ValueError, match="Conflicting duplicate PAYMENT_CAPTURE"):
        build_graph(orders, payments + (conflicting_capture,))


def test_repeated_delivery_uses_one_webhook_node_and_retains_receipt_times():
    orders, payments, events, _business = build_synthetic_lineage_records()
    second_delivery = events[0].model_copy(
        update={"received_at": events[0].received_at + timedelta(seconds=30)}
    )
    result = build_graph(orders, payments, events + (second_delivery,))
    webhook_nodes = [
        attributes
        for _, attributes in result.nodes
        if attributes["node_type"] == NodeType.WEBHOOK_EVENT.value
    ]

    assert len(webhook_nodes) == 1
    assert "receipt_timestamp" not in webhook_nodes[0]
    assert webhook_nodes[0]["metadata"]["delivery_receipt_timestamps"] == (
        events[0].received_at,
        second_delivery.received_at,
    )


def test_unresolved_webhook_resource_is_reported_without_creating_an_edge():
    _orders, _payments, events, _business = build_synthetic_lineage_records()
    event = events[0].model_copy(
        update={"related_resource_id": "SYNTH-RESOURCE-NOT-SUPPLIED"}
    )
    result = build_graph(webhook_events=(event,))

    assert not result.edges
    assert len(result.missing_relationship_endpoints) == 1
    missing = result.missing_relationship_endpoints[0]
    assert missing.relationship_type == RelationshipType.NOTIFIED_BY
    assert missing.endpoint_node_type is None
    assert missing.external_record_id == "SYNTH-RESOURCE-NOT-SUPPLIED"
    assert missing.evidence_reference == event.paypal_event_id


def test_webhook_does_not_link_to_merchant_node_with_coincident_external_id():
    orders, _payments, events, _business = build_synthetic_lineage_records()
    order = orders[0].model_copy(
        update={"merchant_order_id": events[0].related_resource_id}
    )
    result = build_graph(merchant_orders=(order,), webhook_events=events)

    assert not result.edges
    assert len(result.missing_relationship_endpoints) == 1
    assert result.missing_relationship_endpoints[0].relationship_type == (
        RelationshipType.NOTIFIED_BY
    )


def test_ambiguous_paypal_webhook_resource_reports_candidate_nodes():
    orders, payments, events, _business = build_synthetic_lineage_records()
    matching_order = payments[0].model_copy(
        update={
            "paypal_order_id": events[0].related_resource_id,
            "paypal_capture_id": "SYNTH-OTHER-CAPTURE",
        }
    )
    matching_capture = payments[0].model_copy(
        update={"paypal_capture_id": events[0].related_resource_id}
    )
    result = build_graph(orders, (matching_order, matching_capture), events)

    missing = next(
        item
        for item in result.missing_relationship_endpoints
        if item.relationship_type == RelationshipType.NOTIFIED_BY
    )
    assert len(missing.candidate_node_ids) == 2
    assert all(
        node_id in result.graph
        for node_id in missing.candidate_node_ids
    )


def test_matching_amount_and_timestamp_do_not_create_relationships():
    orders, _payments, events, _business = build_synthetic_lineage_records()
    unmatched_event = events[0].model_copy(
        update={"related_resource_id": "SYNTH-NO-RECORD-WITH-THIS-ID"}
    )
    result = build_graph(merchant_orders=orders, webhook_events=(unmatched_event,))

    assert not result.edges
    assert result.missing_relationship_endpoints[0].relationship_type == (
        RelationshipType.NOTIFIED_BY
    )


def test_webhook_can_reference_a_business_node_added_later():
    orders, payments, events, business = build_synthetic_lineage_records()
    refund_id = "SYNTH-LINEAGE-PAYPAL-REFUND-LATE"
    event = events[0].model_copy(
        update={"related_resource_id": refund_id}
    )
    paypal_refund_business = business[0].model_copy(
        update={
            "refund_records": [
                {
                    "paypal_refund_id": refund_id,
                    "capture_id": payments[0].paypal_capture_id,
                }
            ]
        }
    )
    result = build_graph(orders, payments, (event,), (paypal_refund_business,))

    assert any(
        result.graph.nodes[source]["node_type"] == NodeType.REFUND_RECORD.value
        and result.graph.nodes[target]["node_type"] == NodeType.WEBHOOK_EVENT.value
        and attributes["relationship_type"] == RelationshipType.NOTIFIED_BY.value
        for source, target, attributes in result.edges
    )
    assert not any(
        missing.relationship_type == RelationshipType.NOTIFIED_BY
        for missing in result.missing_relationship_endpoints
    )


def test_missing_parent_does_not_connect_disconnected_fulfillment_or_accounting():
    _orders, _payments, _events, business = build_synthetic_lineage_records()
    record = business[0].model_copy(
        update={
            "merchant_order_id": "SYNTH-MISSING-PARENT",
            "updated_by_event_id": None,
            "accounting_entries": [
                {"accounting_entry_id": "SYNTH-DISCONNECTED-ENTRY"}
            ],
            "refund_records": [
                {"refund_id": "SYNTH-DISCONNECTED-REFUND"}
            ],
        }
    )
    result = build_graph(business_records=(record,))

    relationship_types = _relationship_types(result)
    assert RelationshipType.FULFILLED_BY not in relationship_types
    assert RelationshipType.RECORDED_IN not in relationship_types
    assert RelationshipType.REFUNDED_BY not in relationship_types
    missing = {
        (item.relationship_type, item.external_record_id, item.evidence_reference)
        for item in result.missing_relationship_endpoints
    }
    assert (
        RelationshipType.FULFILLED_BY,
        "SYNTH-MISSING-PARENT",
        "SYNTH-LINEAGE-FULFILLMENT-001",
    ) in missing
    assert (
        RelationshipType.RECORDED_IN,
        "SYNTH-MISSING-PARENT",
        "SYNTH-DISCONNECTED-ENTRY",
    ) in missing
    assert (
        RelationshipType.REFUNDED_BY,
        "SYNTH-MISSING-PARENT",
        "SYNTH-DISCONNECTED-REFUND",
    ) in missing


def test_top_level_update_reference_is_not_dropped_without_fulfillment_id():
    orders, _payments, events, business = build_synthetic_lineage_records()
    record = business[0].model_copy(
        update={
            "fulfillment_record_id": None,
            "shipping_information": {"shipping_record_id": "SYNTH-SHIPPING"},
        }
    )
    result = build_graph(orders, webhook_events=events, business_records=(record,))

    assert any(
        result.graph.nodes[source]["node_type"] == NodeType.MERCHANT_ORDER.value
        and result.graph.nodes[target]["node_type"] == NodeType.WEBHOOK_EVENT.value
        and attributes["relationship_type"] == RelationshipType.UPDATED_BY.value
        for source, target, attributes in result.edges
    )


def test_conflicting_fulfillment_ids_are_rejected():
    _orders, _payments, _events, business = build_synthetic_lineage_records()
    record = business[0].model_copy(
        update={
            "shipping_information": {
                **business[0].shipping_information,
                "fulfillment_record_id": "SYNTH-OTHER-FULFILLMENT",
            }
        }
    )

    with pytest.raises(ValueError, match="Conflicting fulfillment record IDs"):
        build_graph(business_records=(record,))


def test_missing_capture_id_is_not_fabricated():
    orders, payments, _events, _business = build_synthetic_lineage_records()
    payment = payments[0].model_copy(update={"paypal_capture_id": None})
    result = build_graph(orders, (payment,))

    assert all(
        attributes["node_type"] != NodeType.PAYMENT_CAPTURE.value
        for _, attributes in result.nodes
    )
    assert any(
        missing.relationship_type == RelationshipType.CAPTURED_AS
        and missing.external_record_id is None
        for missing in result.missing_relationship_endpoints
    )


def test_business_records_without_explicit_ids_do_not_create_nodes():
    orders, _payments, _events, business = build_synthetic_lineage_records()
    record = business[0].model_copy(
        update={
            "fulfillment_record_id": None,
            "shipping_information": {"status": "in_transit"},
            "accounting_entries": [{"amount": Decimal("100"), "currency": "USD"}],
            "refund_records": [{"amount": Decimal("5"), "currency": "USD"}],
        }
    )
    result = build_graph(orders, business_records=(record,))

    assert {attributes["node_type"] for _, attributes in result.nodes} == {
        NodeType.MERCHANT_ORDER.value
    }
    assert {
        missing.relationship_type for missing in result.missing_relationship_endpoints
    } == {
        RelationshipType.FULFILLED_BY,
        RelationshipType.SHIPPED_AS,
        RelationshipType.RECORDED_IN,
        RelationshipType.REFUNDED_BY,
        RelationshipType.UPDATED_BY,
    }


def test_missing_accounting_and_refund_ids_report_update_reference():
    orders, _payments, _events, business = build_synthetic_lineage_records()
    record = business[0].model_copy(
        update={
            "fulfillment_record_id": None,
            "updated_by_event_id": None,
            "shipping_information": None,
            "accounting_entries": [
                {"updated_by_event_id": "SYNTH-ACCOUNTING-EVENT"}
            ],
            "refund_records": [{"updated_by_event_id": "SYNTH-REFUND-EVENT"}],
        }
    )
    result = build_graph(orders, business_records=(record,))

    missing_updates = {
        missing.evidence_reference: missing
        for missing in result.missing_relationship_endpoints
        if missing.relationship_type == RelationshipType.UPDATED_BY
    }
    assert missing_updates["SYNTH-ACCOUNTING-EVENT"].endpoint_node_type == (
        NodeType.ACCOUNTING_ENTRY
    )
    assert missing_updates["SYNTH-REFUND-EVENT"].endpoint_node_type == (
        NodeType.REFUND_RECORD
    )


@pytest.mark.parametrize(
    "record",
    [
        {"accounting_entry_id": 123},
        {"accounting_entry_id": "SYNTH-ENTRY", "status": 1},
    ],
)
def test_malformed_business_ids_and_text_fields_are_rejected(record):
    orders, _payments, _events, business = build_synthetic_lineage_records()
    record_with_entry = business[0].model_copy(
        update={
            "fulfillment_record_id": None,
            "updated_by_event_id": None,
            "shipping_information": None,
            "accounting_entries": [record],
            "refund_records": [],
        }
    )

    with pytest.raises(ValueError):
        build_graph(orders, business_records=(record_with_entry,))


def test_missing_order_and_capture_references_are_reported():
    _orders, payments, _events, _business = build_synthetic_lineage_records()
    payment = payments[0].model_copy(
        update={"merchant_order_id": "SYNTH-ORDER-NOT-SUPPLIED"}
    )
    result = build_graph(paypal_payments=(payment,))

    missing_types = {
        missing.relationship_type for missing in result.missing_relationship_endpoints
    }
    assert RelationshipType.CREATED_FROM in missing_types
    assert RelationshipType.ASSOCIATED_WITH in missing_types
    assert not any(
        attributes["relationship_type"] == RelationshipType.CREATED_FROM.value
        for _, _, attributes in result.edges
    )


def test_conflicting_duplicate_event_identity_is_rejected():
    _orders, _payments, events, _business = build_synthetic_lineage_records()
    conflicting = events[0].model_copy(update={"event_type": "SYNTHETIC.OTHER"})

    with pytest.raises(ValueError, match="Conflicting duplicate webhook event"):
        LineageGraphBuilder().build(webhook_events=events + (conflicting,))


def test_out_of_order_webhook_arrival_does_not_change_event_timestamps():
    orders, payments, events, _business = build_synthetic_lineage_records()
    later_event = events[0].model_copy(
        update={
            "paypal_event_id": "SYNTH-EVENT-LATER",
            "occurred_at": events[0].occurred_at + timedelta(minutes=2),
            "received_at": events[0].received_at - timedelta(minutes=1),
        }
    )
    result = build_graph(orders, payments, events + (later_event,))
    webhook_occurrences = [
        attributes["occurrence_timestamp"]
        for _, attributes in result.nodes
        if attributes["node_type"] == NodeType.WEBHOOK_EVENT.value
    ]

    assert set(webhook_occurrences) == {events[0].occurred_at, later_event.occurred_at}
    assert result.missing_relationship_endpoints == ()
