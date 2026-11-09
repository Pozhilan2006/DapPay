# Payment event lineage graph (provisional)

## Scope

`backend/app/lineage/graph_builder.py` builds an in-memory NetworkX
`MultiDiGraph` from the provisional payment DTOs. It performs no database,
FastAPI, PayPal API, or persistence operations and does not change existing API
contracts. It is not a final Member 1 schema or a production event store.

The builder returns `LineageGraph`, containing the directed graph and a
`missing_relationship_endpoints` collection. Graph node IDs are stable,
URL-escaped combinations of node type, source system, and supplied external
record ID. Duplicate records with identical attributes reuse one node; the same
source identity with conflicting attributes is rejected instead of silently
overwritten. Duplicate edges with the same endpoints, type, evidence, and
timestamp are idempotent.

## Node data

Supported node types:

- `MERCHANT_ORDER`
- `PAYPAL_ORDER`
- `PAYMENT_CAPTURE`
- `WEBHOOK_EVENT`
- `FULFILLMENT_RECORD`
- `SHIPPING_RECORD`
- `REFUND_RECORD`
- `ACCOUNTING_ENTRY`

Each node includes `node_id`, `node_type`, `source_system`, and
`external_record_id`. Status, amount, currency, occurrence/receipt timestamps,
and metadata are included only when present in the input. DTO timestamps remain
separate: capture occurrence uses `capture_timestamp`; webhook event
occurrence and delivery receipt use `occurred_at` and `received_at`. Multiple
deliveries of one PayPal event ID produce one event node, retain all distinct
receipt timestamps in metadata, and do not create extra financial nodes.

Merchant business records are provisional mappings. The graph builder
recognizes these explicit ID keys:

- `fulfillment_record_id` on the business DTO, or in its shipping information.
- `shipping_record_id` in `shipping_information`.
- `accounting_entry_id` in an accounting entry.
- `refund_record_id`, `paypal_refund_id`, or `refund_id` in a refund record.
- `capture_id` for a refund/accounting-entry capture reference.
- `updated_by_event_id` for explicit webhook-to-business-record lineage.

When a required record ID is absent, no node is fabricated. If a relationship
was otherwise implied by a supplied parent/reference, the missing endpoint is
reported with the relationship type, supplied reference (if any), and reason.
The opaque business-record dictionary shapes and optional DTO ID additions are
provisional and require Member 1 confirmation.

## Directed relationship meanings

Every edge carries `source_node_id`, `target_node_id`,
`relationship_type`, and an evidence reference. `relationship_timestamp` is
present only when an input timestamp supports it.

| Relationship | Direction | Evidence used |
|---|---|---|
| `CREATED_FROM` | PayPal order → merchant order | A payment record explicitly supplies both IDs via its PayPal order ID and merchant order ID. |
| `ASSOCIATED_WITH` | Merchant order → PayPal order and capture | The payment record explicitly links those records through merchant order ID and its PayPal identifiers. |
| `CAPTURED_AS` | PayPal order → payment capture | Both PayPal order ID and capture ID occur on the payment record. |
| `NOTIFIED_BY` | Related PayPal resource → webhook event | Webhook `related_resource_id` uniquely resolves to a supplied PayPal-source node ID. |
| `UPDATED_BY` | Business record → webhook event | Business record explicitly supplies `updated_by_event_id`. |
| `FULFILLED_BY` | Merchant order → fulfillment record | The business record has an explicit fulfillment record ID and merchant order ID. |
| `SHIPPED_AS` | Fulfillment record → shipping record | Both record IDs are explicitly supplied. |
| `REFUNDED_BY` | Merchant order or capture → refund record | Refund record is nested under the merchant-order business record, or has an explicit capture ID. |
| `RECORDED_IN` | Merchant order or capture → accounting entry | Accounting entry is nested under the order business record, or has an explicit capture ID. |

No edge is created from matching amounts or timestamps. Webhook resource IDs
are resolved only against PayPal-source nodes; coincidentally matching merchant
IDs do not establish an edge. Missing or ambiguous PayPal resource IDs are
reported with the event ID, resource ID, reason, and ambiguous candidate node
IDs. Arrival order is not treated as transaction lifecycle order.

## Synthetic data and limitations

`backend/tests/fixtures/synthetic_lineage.py` contains explicitly synthetic
IDs, payment records, webhook payloads, and merchant records. These fixtures
are not real PayPal transactions, sandbox responses, or production merchant
records.

The current payment DTO exposes merchant order ID, PayPal order ID, and capture
ID together on a payment record, but Member 1 has not confirmed the shared key
semantics or source guarantees. Fulfillment, shipping, accounting, and refund
records remain opaque dictionaries. Status/event vocabularies and timestamp
semantics beyond the DTO field names require confirmation. The existing
`timeline.py` chronological API remains outside this implementation because
the supplied Task 3 requirements ended mid-Step 4; the graph retains available
event timestamps without imposing a lifecycle order.

Before production integration, confirm the record IDs and explicit foreign
references, refund and business-record shapes, event-to-resource association,
source-system naming, and timestamp semantics with Member 1. Then map confirmed
records into the graph builder without creating duplicate database models.
