"""Build an in-memory directed lineage graph from provisional records."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import networkx as nx

from app.integration_contracts.payment_data import (
    ProvisionalMerchantBusinessRecords,
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
    ProvisionalWebhookEvent,
)
from app.lineage.relationships import RelationshipType


class NodeType(StrEnum):
    MERCHANT_ORDER = "MERCHANT_ORDER"
    PAYPAL_ORDER = "PAYPAL_ORDER"
    PAYMENT_CAPTURE = "PAYMENT_CAPTURE"
    WEBHOOK_EVENT = "WEBHOOK_EVENT"
    FULFILLMENT_RECORD = "FULFILLMENT_RECORD"
    SHIPPING_RECORD = "SHIPPING_RECORD"
    REFUND_RECORD = "REFUND_RECORD"
    ACCOUNTING_ENTRY = "ACCOUNTING_ENTRY"


@dataclass(frozen=True)
class MissingRelationshipEndpoint:
    relationship_type: RelationshipType
    endpoint_node_type: NodeType | None
    external_record_id: str | None
    evidence_reference: str | None
    reason: str
    candidate_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LineageGraph:
    graph: nx.MultiDiGraph
    missing_relationship_endpoints: tuple[MissingRelationshipEndpoint, ...]

    @property
    def nodes(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple(self.graph.nodes(data=True))

    @property
    def edges(self) -> tuple[tuple[str, str, dict[str, Any]], ...]:
        return tuple(
            (source, target, attributes)
            for source, target, _key, attributes in self.graph.edges(
                keys=True, data=True
            )
        )


class LineageGraphBuilder:
    def build(
        self,
        merchant_orders: Sequence[ProvisionalMerchantOrder] = (),
        paypal_payments: Sequence[ProvisionalPayPalPayment] = (),
        webhook_events: Sequence[ProvisionalWebhookEvent] = (),
        business_records: Sequence[ProvisionalMerchantBusinessRecords] = (),
    ) -> LineageGraph:
        graph = nx.MultiDiGraph()
        missing: list[MissingRelationshipEndpoint] = []
        missing_keys: set[tuple[Any, ...]] = set()
        external_nodes: dict[str, list[str]] = {}
        order_nodes: dict[str, str] = {}
        capture_nodes: dict[str, str] = {}
        webhook_nodes: dict[str, str] = {}

        def add_node(
            *,
            node_type: NodeType,
            source_system: str,
            external_record_id: str,
            status: str | None = None,
            amount: Decimal | None = None,
            currency: str | None = None,
            occurrence_timestamp: datetime | None = None,
            receipt_timestamp: datetime | None = None,
            metadata: Mapping[str, Any] | None = None,
        ) -> str:
            if not external_record_id.strip():
                raise ValueError(
                    f"{node_type.value} external record ID cannot be empty"
                )
            node_id = _node_id(node_type, source_system, external_record_id)
            attributes: dict[str, Any] = {
                "node_id": node_id,
                "node_type": node_type.value,
                "source_system": source_system,
                "external_record_id": external_record_id,
            }
            optional_values = {
                "status": status,
                "amount": amount,
                "currency": currency,
                "occurrence_timestamp": occurrence_timestamp,
                "receipt_timestamp": receipt_timestamp,
            }
            attributes.update(
                {
                    key: value
                    for key, value in optional_values.items()
                    if value is not None
                }
            )
            if metadata:
                attributes["metadata"] = dict(metadata)

            if graph.has_node(node_id):
                existing = graph.nodes[node_id]
                if existing != attributes:
                    raise ValueError(
                        f"Conflicting duplicate {node_type.value} record: "
                        f"{external_record_id}"
                    )
            else:
                graph.add_node(node_id, **attributes)
                external_nodes.setdefault(external_record_id, []).append(node_id)
            return node_id

        def add_missing(
            relationship_type: RelationshipType,
            endpoint_node_type: NodeType | None,
            external_record_id: str | None,
            evidence_reference: str | None,
            reason: str,
            candidate_node_ids: Sequence[str] = (),
        ) -> None:
            item = MissingRelationshipEndpoint(
                relationship_type=relationship_type,
                endpoint_node_type=endpoint_node_type,
                external_record_id=external_record_id,
                evidence_reference=evidence_reference,
                reason=reason,
                candidate_node_ids=tuple(sorted(candidate_node_ids)),
            )
            key = (
                item.relationship_type,
                item.endpoint_node_type,
                item.external_record_id,
                item.evidence_reference,
                item.reason,
            )
            if key not in missing_keys:
                missing.append(item)
                missing_keys.add(key)

        def add_edge(
            source_id: str | None,
            target_id: str | None,
            relationship_type: RelationshipType,
            evidence_reference: str | None,
            relationship_timestamp: datetime | None = None,
        ) -> None:
            if source_id is None or target_id is None:
                return
            identity = {
                "relationship_type": relationship_type.value,
                "evidence_reference": evidence_reference,
                "relationship_timestamp": (
                    relationship_timestamp.isoformat()
                    if relationship_timestamp is not None
                    else None
                ),
            }
            edge_key = hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode("utf-8")
            ).hexdigest()
            attributes = {
                "source_node_id": source_id,
                "target_node_id": target_id,
                "relationship_type": relationship_type.value,
                "evidence_reference": evidence_reference,
            }
            if relationship_timestamp is not None:
                attributes["relationship_timestamp"] = relationship_timestamp
            if not graph.has_edge(source_id, target_id, edge_key):
                graph.add_edge(source_id, target_id, key=edge_key, **attributes)

        for order in merchant_orders:
            node_id = add_node(
                node_type=NodeType.MERCHANT_ORDER,
                source_system="merchant",
                external_record_id=order.merchant_order_id,
                status=order.order_status,
                amount=order.expected_amount,
                currency=order.currency,
                occurrence_timestamp=order.order_created_at,
                metadata=_nonempty_metadata(
                    {"customer_reference": order.customer_reference}
                ),
            )
            _add_unique_mapping(order_nodes, order.merchant_order_id, node_id)

        for payment in paypal_payments:
            paypal_order_id = add_node(
                node_type=NodeType.PAYPAL_ORDER,
                source_system="paypal",
                external_record_id=payment.paypal_order_id,
            )
            merchant_order_node = order_nodes.get(payment.merchant_order_id)
            if merchant_order_node is None:
                add_missing(
                    RelationshipType.CREATED_FROM,
                    NodeType.MERCHANT_ORDER,
                    payment.merchant_order_id,
                    payment.paypal_order_id,
                    "Payment references a merchant order that was not supplied.",
                )
                add_missing(
                    RelationshipType.ASSOCIATED_WITH,
                    NodeType.MERCHANT_ORDER,
                    payment.merchant_order_id,
                    payment.paypal_order_id,
                    "Payment references a merchant order that was not supplied.",
                )
            else:
                add_edge(
                    paypal_order_id,
                    merchant_order_node,
                    RelationshipType.CREATED_FROM,
                    payment.paypal_order_id,
                )
                add_edge(
                    merchant_order_node,
                    paypal_order_id,
                    RelationshipType.ASSOCIATED_WITH,
                    payment.paypal_order_id,
                )

            if payment.paypal_capture_id is None:
                add_missing(
                    RelationshipType.CAPTURED_AS,
                    NodeType.PAYMENT_CAPTURE,
                    None,
                    payment.paypal_order_id,
                    "Payment record has no PayPal capture ID.",
                )
                continue
            capture_id = add_node(
                node_type=NodeType.PAYMENT_CAPTURE,
                source_system="paypal",
                external_record_id=payment.paypal_capture_id,
                status=payment.capture_status,
                amount=payment.actual_payment_amount,
                currency=payment.currency,
                occurrence_timestamp=payment.capture_timestamp,
                metadata={"paypal_order_id": payment.paypal_order_id},
            )
            _add_unique_mapping(capture_nodes, payment.paypal_capture_id, capture_id)
            add_edge(
                paypal_order_id,
                capture_id,
                RelationshipType.CAPTURED_AS,
                payment.paypal_capture_id,
                payment.capture_timestamp,
            )
            if merchant_order_node is not None:
                add_edge(
                    merchant_order_node,
                    capture_id,
                    RelationshipType.ASSOCIATED_WITH,
                    payment.paypal_capture_id,
                    payment.capture_timestamp,
                )

        events_by_id: dict[str, list[ProvisionalWebhookEvent]] = {}
        for event in webhook_events:
            events_by_id.setdefault(event.paypal_event_id, []).append(event)

        pending_webhook_links: list[tuple[str, str, datetime]] = []
        for event_id, deliveries in events_by_id.items():
            event = deliveries[0]
            if any(
                (
                    delivery.event_type,
                    delivery.related_resource_id,
                    delivery.occurred_at,
                    delivery.verification_status,
                    delivery.original_event_payload,
                )
                != (
                    event.event_type,
                    event.related_resource_id,
                    event.occurred_at,
                    event.verification_status,
                    event.original_event_payload,
                )
                for delivery in deliveries[1:]
            ):
                raise ValueError(f"Conflicting duplicate webhook event: {event_id}")
            receipt_timestamps = tuple(
                sorted({delivery.received_at for delivery in deliveries})
            )
            event_metadata: dict[str, Any] = {
                "event_type": event.event_type,
                "verification_status": event.verification_status,
                "original_event_payload": event.original_event_payload,
            }
            if len(receipt_timestamps) > 1:
                event_metadata["delivery_receipt_timestamps"] = receipt_timestamps
            event_node = add_node(
                node_type=NodeType.WEBHOOK_EVENT,
                source_system="paypal",
                external_record_id=event_id,
                occurrence_timestamp=event.occurred_at,
                receipt_timestamp=(
                    receipt_timestamps[0]
                    if len(receipt_timestamps) == 1
                    else None
                ),
                metadata=event_metadata,
            )
            _add_unique_mapping(webhook_nodes, event_id, event_node)
            pending_webhook_links.append(
                (event_id, event.related_resource_id, event.occurred_at)
            )

        for business_record in business_records:
            order_node = order_nodes.get(business_record.merchant_order_id)
            shipping = business_record.shipping_information
            shipping_fulfillment_id = (
                _record_id(shipping, "fulfillment_record_id")
                if shipping is not None
                else None
            )
            if (
                business_record.fulfillment_record_id is not None
                and shipping_fulfillment_id is not None
                and business_record.fulfillment_record_id != shipping_fulfillment_id
            ):
                raise ValueError(
                    "Conflicting fulfillment record IDs in business record "
                    f"{business_record.merchant_order_id}"
                )
            fulfillment_id = (
                business_record.fulfillment_record_id or shipping_fulfillment_id
            )
            fulfillment_node: str | None = None
            if fulfillment_id is not None:
                fulfillment_node = add_node(
                    node_type=NodeType.FULFILLMENT_RECORD,
                    source_system="merchant",
                    external_record_id=fulfillment_id,
                    status=business_record.fulfillment_status,
                    metadata=_nonempty_metadata(
                        {"merchant_order_id": business_record.merchant_order_id}
                    ),
                )
                if order_node is None:
                    add_missing(
                        RelationshipType.FULFILLED_BY,
                        NodeType.MERCHANT_ORDER,
                        business_record.merchant_order_id,
                        fulfillment_id,
                        "Fulfillment record references a merchant order "
                        "that was not supplied.",
                    )
                else:
                    add_edge(
                        order_node,
                        fulfillment_node,
                        RelationshipType.FULFILLED_BY,
                        business_record.merchant_order_id,
                    )
                _connect_updated_by_event(
                    fulfillment_node,
                    business_record.updated_by_event_id,
                    webhook_nodes,
                    add_edge,
                    add_missing,
                    NodeType.FULFILLMENT_RECORD,
                    fulfillment_id,
                )
            elif business_record.fulfillment_status is not None:
                add_missing(
                    RelationshipType.FULFILLED_BY,
                    NodeType.FULFILLMENT_RECORD,
                    None,
                    business_record.merchant_order_id,
                    "Fulfillment status is present without a fulfillment record ID.",
                )

            if (
                business_record.updated_by_event_id is not None
                and fulfillment_node is None
            ):
                if order_node is not None:
                    _connect_updated_by_event(
                        order_node,
                        business_record.updated_by_event_id,
                        webhook_nodes,
                        add_edge,
                        add_missing,
                        NodeType.MERCHANT_ORDER,
                        business_record.merchant_order_id,
                    )
                else:
                    add_missing(
                        RelationshipType.UPDATED_BY,
                        NodeType.MERCHANT_ORDER,
                        business_record.merchant_order_id,
                        business_record.updated_by_event_id,
                        "Updated business record's merchant order was not supplied.",
                    )

            if shipping is not None:
                shipping_id = _record_id(shipping, "shipping_record_id")
                shipping_node: str | None = None
                if shipping_id is not None:
                    shipping_node = add_node(
                        node_type=NodeType.SHIPPING_RECORD,
                        source_system="merchant",
                        external_record_id=shipping_id,
                        status=_optional_string(shipping.get("status")),
                        amount=_optional_decimal(shipping.get("amount")),
                        currency=_optional_string(shipping.get("currency")),
                        occurrence_timestamp=_record_timestamp(
                            shipping, "occurred_at"
                        ),
                        receipt_timestamp=_record_timestamp(shipping, "received_at"),
                        metadata=_record_metadata(
                            shipping,
                            {
                                "shipping_record_id",
                                "status",
                                "amount",
                                "currency",
                                "occurred_at",
                                "received_at",
                                "fulfillment_record_id",
                                "updated_by_event_id",
                            },
                        ),
                    )
                if fulfillment_node is None:
                    add_missing(
                        RelationshipType.SHIPPED_AS,
                        NodeType.FULFILLMENT_RECORD,
                        fulfillment_id,
                        shipping_id or business_record.merchant_order_id,
                        "Shipping information has no supplied fulfillment record ID.",
                    )
                elif shipping_node is None:
                    add_missing(
                        RelationshipType.SHIPPED_AS,
                        NodeType.SHIPPING_RECORD,
                        None,
                        fulfillment_id,
                        "Shipping information has no shipping record ID.",
                    )
                else:
                    add_edge(
                        fulfillment_node,
                        shipping_node,
                        RelationshipType.SHIPPED_AS,
                        shipping_id,
                        _record_timestamp(shipping, "occurred_at"),
                    )
                if shipping_node is not None:
                    _connect_updated_by_event(
                        shipping_node,
                        _optional_string(shipping.get("updated_by_event_id")),
                        webhook_nodes,
                        add_edge,
                        add_missing,
                        NodeType.SHIPPING_RECORD,
                        shipping_id,
                    )

            for entry in business_record.accounting_entries:
                entry_id = _record_id(entry, "accounting_entry_id")
                if entry_id is None:
                    add_missing(
                        RelationshipType.RECORDED_IN,
                        NodeType.ACCOUNTING_ENTRY,
                        None,
                        business_record.merchant_order_id,
                        "Accounting entry has no accounting_entry_id.",
                    )
                    entry_event_id = _optional_string(
                        entry.get("updated_by_event_id")
                    )
                    if entry_event_id is not None:
                        add_missing(
                            RelationshipType.UPDATED_BY,
                            NodeType.ACCOUNTING_ENTRY,
                            None,
                            entry_event_id,
                            "Updated accounting entry has no accounting_entry_id.",
                        )
                    continue
                entry_node = add_node(
                    node_type=NodeType.ACCOUNTING_ENTRY,
                    source_system=_optional_string(entry.get("source_system"))
                    or "merchant",
                    external_record_id=entry_id,
                    status=_optional_string(entry.get("status")),
                    amount=_optional_decimal(entry.get("amount")),
                    currency=_optional_string(entry.get("currency")),
                    occurrence_timestamp=_record_timestamp(entry, "occurred_at"),
                    receipt_timestamp=_record_timestamp(entry, "received_at"),
                    metadata=_record_metadata(
                        entry,
                        {
                            "accounting_entry_id",
                            "source_system",
                            "status",
                            "amount",
                            "currency",
                            "occurred_at",
                            "received_at",
                            "capture_id",
                            "updated_by_event_id",
                        },
                    ),
                )
                capture_reference = _optional_string(entry.get("capture_id"))
                source_node = capture_nodes.get(capture_reference or "")
                if capture_reference is not None and source_node is None:
                    add_missing(
                        RelationshipType.RECORDED_IN,
                        NodeType.PAYMENT_CAPTURE,
                        capture_reference,
                        entry_id,
                        "Accounting entry references a capture that was not supplied.",
                    )
                elif source_node is None:
                    source_node = order_node
                    if source_node is None:
                        add_missing(
                            RelationshipType.RECORDED_IN,
                            NodeType.MERCHANT_ORDER,
                            business_record.merchant_order_id,
                            entry_id,
                            "Accounting entry's merchant order was not supplied.",
                        )
                if source_node is not None:
                    add_edge(
                        source_node,
                        entry_node,
                        RelationshipType.RECORDED_IN,
                        capture_reference or business_record.merchant_order_id,
                        _record_timestamp(entry, "occurred_at"),
                    )
                _connect_updated_by_event(
                    entry_node,
                    _optional_string(entry.get("updated_by_event_id")),
                    webhook_nodes,
                    add_edge,
                    add_missing,
                    NodeType.ACCOUNTING_ENTRY,
                    entry_id,
                )

            for refund in business_record.refund_records:
                refund_id = _record_id(
                    refund, "refund_record_id", "paypal_refund_id", "refund_id"
                )
                if refund_id is None:
                    add_missing(
                        RelationshipType.REFUNDED_BY,
                        NodeType.REFUND_RECORD,
                        None,
                        business_record.merchant_order_id,
                        "Refund record has no refund_record_id, "
                        "paypal_refund_id, or refund_id.",
                    )
                    refund_event_id = _optional_string(
                        refund.get("updated_by_event_id")
                    )
                    if refund_event_id is not None:
                        add_missing(
                            RelationshipType.UPDATED_BY,
                            NodeType.REFUND_RECORD,
                            None,
                            refund_event_id,
                            "Updated refund record has no refund record ID.",
                        )
                    continue
                refund_source = (
                    "paypal"
                    if refund.get("paypal_refund_id") is not None
                    else "merchant"
                )
                refund_node = add_node(
                    node_type=NodeType.REFUND_RECORD,
                    source_system=_optional_string(refund.get("source_system"))
                    or refund_source,
                    external_record_id=refund_id,
                    status=_optional_string(refund.get("status")),
                    amount=_optional_decimal(refund.get("amount")),
                    currency=_optional_string(refund.get("currency")),
                    occurrence_timestamp=_record_timestamp(refund, "occurred_at"),
                    receipt_timestamp=_record_timestamp(refund, "received_at"),
                    metadata=_record_metadata(
                        refund,
                        {
                            "refund_record_id",
                            "paypal_refund_id",
                            "refund_id",
                            "source_system",
                            "status",
                            "amount",
                            "currency",
                            "occurred_at",
                            "received_at",
                            "capture_id",
                            "updated_by_event_id",
                        },
                    ),
                )
                capture_reference = _optional_string(refund.get("capture_id"))
                source_node = capture_nodes.get(capture_reference or "")
                if capture_reference is not None and source_node is None:
                    add_missing(
                        RelationshipType.REFUNDED_BY,
                        NodeType.PAYMENT_CAPTURE,
                        capture_reference,
                        refund_id,
                        "Refund record references a capture that was not supplied.",
                    )
                elif source_node is None:
                    source_node = order_node
                    if source_node is None:
                        add_missing(
                            RelationshipType.REFUNDED_BY,
                            NodeType.MERCHANT_ORDER,
                            business_record.merchant_order_id,
                            refund_id,
                            "Refund record's merchant order was not supplied.",
                        )
                if source_node is not None:
                    add_edge(
                        source_node,
                        refund_node,
                        RelationshipType.REFUNDED_BY,
                        capture_reference or business_record.merchant_order_id,
                        _record_timestamp(refund, "occurred_at"),
                    )
                _connect_updated_by_event(
                    refund_node,
                    _optional_string(refund.get("updated_by_event_id")),
                    webhook_nodes,
                    add_edge,
                    add_missing,
                    NodeType.REFUND_RECORD,
                    refund_id,
                )

        for event_id, resource_id, occurred_at in pending_webhook_links:
            event_node = webhook_nodes[event_id]
            candidates = [
                node_id
                for node_id in external_nodes.get(resource_id, [])
                if graph.nodes[node_id]["source_system"] == "paypal"
                and graph.nodes[node_id]["node_type"] != NodeType.WEBHOOK_EVENT.value
            ]
            if len(candidates) == 1:
                add_edge(
                    candidates[0],
                    event_node,
                    RelationshipType.NOTIFIED_BY,
                    event_id,
                    occurred_at,
                )
            else:
                add_missing(
                    RelationshipType.NOTIFIED_BY,
                    None,
                    resource_id,
                    event_id,
                    (
                        "Webhook related resource ID does not resolve "
                        "to a supplied node."
                        if not candidates
                        else "Webhook related resource ID is ambiguous "
                        "across supplied nodes."
                    ),
                    candidate_node_ids=candidates,
                )

        return LineageGraph(
            graph=graph,
            missing_relationship_endpoints=tuple(missing),
        )


def build_graph(
    merchant_orders: Sequence[ProvisionalMerchantOrder] = (),
    paypal_payments: Sequence[ProvisionalPayPalPayment] = (),
    webhook_events: Sequence[ProvisionalWebhookEvent] = (),
    business_records: Sequence[ProvisionalMerchantBusinessRecords] = (),
) -> LineageGraph:
    """Build a structured graph without database or external-service access."""
    return LineageGraphBuilder().build(
        merchant_orders,
        paypal_payments,
        webhook_events,
        business_records,
    )


def _node_id(node_type: NodeType, source_system: str, external_id: str) -> str:
    return (
        f"{node_type.value}:"
        f"{quote(source_system, safe='')}:"
        f"{quote(external_id, safe='')}"
    )


def _add_unique_mapping(mapping: dict[str, str], key: str, node_id: str) -> None:
    existing = mapping.get(key)
    if existing is not None and existing != node_id:
        raise ValueError(f"Conflicting lineage node mapping for external ID: {key}")
    mapping[key] = node_id


def _connect_updated_by_event(
    business_node: str,
    event_id: str | None,
    webhook_nodes: Mapping[str, str],
    add_edge: Any,
    add_missing: Any,
    node_type: NodeType,
    record_id: str,
) -> None:
    if event_id is None:
        return
    event_node = webhook_nodes.get(event_id)
    if event_node is None:
        add_missing(
            RelationshipType.UPDATED_BY,
            NodeType.WEBHOOK_EVENT,
            event_id,
            record_id,
            "Business record references a webhook event that was not supplied.",
        )
        return
    add_edge(
        business_node,
        event_node,
        RelationshipType.UPDATED_BY,
        event_id,
    )


def _record_id(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string when supplied")
            identifier = value
            if not identifier.strip():
                raise ValueError(f"{key} cannot be empty")
            return identifier
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Lineage text fields must be strings when supplied")
    result = value
    return result if result.strip() else None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Lineage monetary values must not be floats")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"Invalid lineage amount: {value!r}") from error
    if not result.is_finite():
        raise ValueError("Lineage monetary values must be finite")
    return result


def _record_timestamp(record: Mapping[str, Any], key: str) -> datetime | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{key} must be a datetime when supplied")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{key} must be timezone-aware")
    return value


def _record_metadata(
    record: Mapping[str, Any], known_fields: set[str]
) -> dict[str, Any] | None:
    metadata = {key: value for key, value in record.items() if key not in known_fields}
    return metadata or None


def _nonempty_metadata(values: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = {key: value for key, value in values.items() if value is not None}
    return metadata or None
