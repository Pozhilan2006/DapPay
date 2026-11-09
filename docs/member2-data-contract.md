# Member 2 payment data contract (provisional)

## Purpose and status

This document records what the current backend actually provides and the data
Member 2 needs from Member 1. It is an integration-preparation document, not a
database migration or approval of a final schema. The provisional Python DTOs in
[`backend/app/integration_contracts/payment_data.py`](../backend/app/integration_contracts/payment_data.py)
are not SQLAlchemy models and are not wired to API routes or persistence.

Status labels used below:

- **CONFIRMED** — directly present in the inspected repository.
- **PROPOSED** — a consumer-facing contract suggestion, not implemented.
- **MISSING** — not present in the repository.
- **REQUIRES MEMBER 1 CONFIRMATION** — must be agreed before database-dependent
  work or integration.

## Existing backend architecture

- **CONFIRMED:** One FastAPI application is created in `backend/app/main.py`.
  `backend/app/api/router.py` mounts the route modules under `/api`.
- **CONFIRMED:** SQLAlchemy 2 is a dependency and a declarative `Base` exists in
  `backend/app/database/base.py`. Database URL configuration is provided through
  application settings.
- **CONFIRMED:** `backend/app/database/connection.py` creates an engine through
  `get_engine()`. `backend/app/database/session.py` separately creates a module
  level engine and session factory.
- **MISSING:** There are no mapped SQLAlchemy domain models, concrete Pydantic
  API schemas, database migrations, or migration environment in the inspected
  backend. `backend/alembic/versions/` contains only `.gitkeep`.
- **CONFIRMED:** Reconciliation, lineage, anomaly detection, AI investigation,
  and resolution modules are scaffolds/placeholders. They do not consume
  persisted payment, order, or webhook records.
- **CONFIRMED:** `backend/app/integrations/paypal/` contains placeholder helpers.
  The webhook signature helper currently returns `True` unconditionally and
  the normalizer returns its input unchanged; neither establishes verified
  webhook ingestion.
- **CONFIRMED:** No domain status enums were found. Strings such as
  `placeholder`, `not_implemented`, `queued`, and `logged` occur in scaffold
  responses and are not confirmed payment or order lifecycle values. The code
  generally uses snake_case names, but no shared serialized data contract is
  established.
- **CONFIRMED:** The generic `format_amount` helper accepts a `float`; it is not
  a safe monetary type contract. The provisional interfaces use `Decimal`
  instead. The lineage timeline scaffold sorts a generic `created_at` value and
  does not establish webhook or payment timestamp semantics.
- **CONFIRMED:** PayPal order helpers return an empty list or echo an input ID;
  they are placeholders, not real PayPal API results or merchant fixtures.

## Existing database contract

The database schema document lists planned table names, but the names are not
implemented tables. The current model registry and schema package contain no
payment-domain definitions. Consequently, no actual columns, SQL types,
primary/foreign keys, nullability, unique constraints, status enums, or
timestamp semantics can be reported for those domain records.

| Domain record | Table name | Columns and data types | Primary key | Foreign keys | Nullability / unique constraints | Status values | Timestamp semantics |
|---|---|---|---|---|---|---|---|
| Merchant order | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** |
| PayPal payment/capture | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** |
| Webhook event/delivery | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** |
| Fulfillment/shipping record | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** |
| Accounting entry | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** |
| Refund | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** | **MISSING** |

`Base` is the only existing SQLAlchemy model infrastructure; it defines no
table. No existing foreign-key relationships or status enums were found. The
planned names in `docs/database-schema.md` must not be treated as actual
database structures.

## Member 2 input data

The following is the **PROPOSED** minimum read contract. Exact field names,
optionality, status values, and transport representations all **REQUIRE MEMBER
1 CONFIRMATION**.

| Record | Proposed fields | Data and identity requirements |
|---|---|---|
| Merchant order | Merchant order ID, expected amount, currency, order status, order creation timestamp, optional customer reference | Use decimal/numeric money, retain the currency code, and make the merchant order ID distinct from PayPal IDs. |
| PayPal payment/capture | PayPal order ID, PayPal capture ID, merchant order ID, actual payment amount, currency, capture status, capture timestamp | Keep PayPal order ID distinct from capture ID. Represent each capture distinctly if partial or multiple captures are supported; do not infer their behavior until confirmed. |
| Webhook event | PayPal event ID, event type, related resource ID, event occurrence timestamp, event receipt timestamp, verification status, original event payload | Keep the event ID distinct from payment/capture IDs. Preserve occurrence and receipt times separately and retain the original payload if permitted. |
| Merchant business records | Fulfillment status, shipping information, accounting entries, refund records | A merchant API or clearly labelled synthetic fixtures are possible sources. No such source or record shape currently exists. Synthetic records must never be described as real third-party data or integrations. |

### Provisional Python interfaces

The `Provisional*` Pydantic DTOs in
[`payment_data.py`](../backend/app/integration_contracts/payment_data.py) make
the proposed boundary explicit without adding database tables or duplicating
Member 1's models. Monetary fields use `Decimal`; currency is retained as a
string because the accepted code format has not been confirmed. Statuses are
strings, not invented enums. Datetimes are timezone-aware and named separately
for order creation, capture, webhook occurrence, and webhook receipt.

The DTOs are deliberately not consumed by routes, services, or persistence yet.
Their field names and optionality are provisional, and Member 1 must confirm
them before they are treated as an integration contract. Merchant accounting
and refund record internals remain opaque dictionaries until their source
schema is agreed.

For provisional lineage graph construction only,
`ProvisionalMerchantBusinessRecords` additionally accepts optional
`fulfillment_record_id` and `updated_by_event_id` values. These are interface
proposals, not confirmed database columns. The graph adapter recognizes
explicit nested record IDs and references documented in
[`lineage-engine.md`](./lineage-engine.md); it does not infer them from matching
amounts or timestamps.

### Event and financial identity rules

- A webhook event ID identifies an event, not a payment or capture.
- A PayPal order ID and a PayPal capture ID identify different resources.
- A merchant order ID is the merchant-side reference and needs a confirmed
  relationship to PayPal resources.
- Webhook delivery order must not be treated as payment lifecycle order.
- A repeated webhook delivery must not automatically be counted as a repeated
  financial transaction. Event-delivery deduplication and transaction identity
  are separate concerns.
- Amounts must use decimal arithmetic/SQL `NUMERIC`, and the currency code must
  travel with each amount.
- Refunds and partial captures need explicit representation and linkage; these
  cannot be derived from the current code.

## Existing API contracts

The application has no route-level authentication dependency. The placeholder
token helper in `backend/app/core/security.py` is not wired into these routes.
“No auth check” below describes current code only; it is not a security
recommendation.

| Method | Endpoint | Purpose | Required parameters | Response fields currently returned | Authentication | Current implementation status |
|---|---|---|---|---|---|---|
| GET | `/api/health` | Health check | None | `status`, `service` | No route auth check | Implemented health response; not a payment-data API |
| GET | `/api/orders` | List merchant orders | None | `status`, `message` | No route auth check | Placeholder; no order data |
| GET | `/api/orders/{order_id}` | Get an order | Path: `order_id` | `order_id`, `status` | No route auth check | Placeholder; no order lookup |
| GET | `/api/payments` | List payments | None | `status`, `message` | No route auth check | Placeholder; no payment data |
| GET | `/api/payments/{payment_id}` | Get a payment | Path: `payment_id` | `payment_id`, `status` | No route auth check | Placeholder; no payment lookup |
| GET | `/api/webhooks` | List webhook events | None | `status`, `message` | No route auth check | Placeholder; no event data |
| POST | `/api/webhooks` | Receive webhook | No declared body or parameters | `status`, `message` | No route auth check | Placeholder; no ingestion or verification |
| GET | `/api/reconciliation` | Reconciliation status | None | `status`, `message` | No route auth check | Placeholder |
| POST | `/api/reconciliation/run` | Run reconciliation | None | `status`, `message` | No route auth check | Placeholder |
| GET | `/api/lineage` | Get lineage graph | None | `status`, `message` | No route auth check | Placeholder |
| GET | `/api/investigations` | List investigations | None | `status`, `message` | No route auth check | Placeholder |
| POST | `/api/investigations/new` | Create investigation | None | `status`, `message` | No route auth check | Placeholder |

The placeholder response shapes above are the literal fields returned by route
functions, not approved response schemas. No pagination, filters, response
envelopes, error contracts, or API versioning are implemented.

## Proposed API surface

These paths are **PROPOSED**, not usable integrations. The list/detail routes
already exist as placeholders except for webhook-event detail. Member 1 owns
payment and webhook endpoint implementation; this task does not implement
them.

| Method | Endpoint | Purpose | Proposed inputs and output |
|---|---|---|---|
| GET | `/api/orders` | List merchant orders | Confirm pagination/filter parameters and return the agreed merchant order fields. |
| GET | `/api/payments` | List PayPal payment/capture records | Confirm pagination/filter parameters and return the agreed payment/capture fields. |
| GET | `/api/payments/{payment_id}` | Read one payment/capture | Confirm whether `payment_id` means capture ID, database key, or another stable identifier. |
| GET | `/api/webhooks` | List webhook events | Confirm pagination/filter parameters; return separate event occurrence/receipt times and verification status. |
| GET | `/api/webhooks/{event_id}` | Read one webhook event | **MISSING** in current routes; confirm whether `event_id` means the PayPal event ID or an internal key. |

Every proposed route also needs an agreed authentication mechanism, response
schema, error format, and pagination strategy before Member 2 consumes it.

## Integration blockers

1. No confirmed model/table definitions, migrations, keys, or relationships.
2. No usable payment/order/webhook API responses; current routes return
   placeholders.
3. No confirmed identity mapping from merchant order to PayPal order, capture,
   refund, or webhook resource.
4. No agreed status values, capture/refund semantics, or currency/amount wire
   representation.
5. No normalized webhook contract, raw-payload retention decision, signature
   verification contract, or duplicate-delivery semantics.
6. No API authentication, pagination, filtering, or error contract.
7. Merchant fulfillment, shipping, accounting, and refund sources and schemas
   are absent.

Do not implement database-dependent reconciliation logic until Member 1
confirms the shared schema and read API contract.
