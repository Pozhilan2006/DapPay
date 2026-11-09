# Deterministic reconciliation engine

## Scope and input contract

The engine in `backend/app/reconciliation/` is a pure in-memory consumer of
the provisional Pydantic DTOs in
[`payment_data.py`](../backend/app/integration_contracts/payment_data.py). It
does not create or depend on database models, sessions, FastAPI routes, external
services, or the unfinished PayPal integration. It does not change API
contracts and is not wired to an endpoint.

`ReconciliationEngine.run()` accepts merchant orders, PayPal payment/capture
records, optional merchant business records, optional webhook delivery records,
and an optional PayPal refund snapshot. The refund snapshot uses provisional
mapping records containing `merchant_order_id` (or a resolvable `capture_id`),
`amount`, `currency`, and optionally a refund identifier. Refund comparison
runs only when a merchant business record for the order and a PayPal refund
snapshot are both supplied; a missing merchant business record is not
interpreted as zero refunds. `None` means PayPal refund data is unavailable and
skips refund comparison; an empty sequence means the provided PayPal snapshot
contains no refunds.

## Matching strategy

1. Merchant order ID is the primary shared join key in the current provisional
   DTOs. Every capture record with that merchant order ID is retained in the
   same matched transaction.
2. PayPal order ID and capture ID remain distinct payment identifiers, and a
   duplicate non-null capture ID in one input snapshot is rejected to avoid
   double counting.
3. The merchant order DTO has no PayPal order or capture ID, so those IDs
   cannot independently match an order. They are retained for evidence and
   stable case identity. There is no fuzzy amount/customer matching.
4. Duplicate merchant order IDs and duplicate business records for an order are
   rejected as ambiguous input rather than silently selecting a record.
5. Orphan payments and orders without payments are reported as exceptions, not
   labeled fraud.

The current DTOs therefore support the first (merchant-order-ID) matching key
only. If Member 1 cannot reliably supply that link, the minimum additional
contract must expose the PayPal order ID on the merchant order DTO. If
association must fall back directly to capture ID, Member 1 must expose an
explicit merchant-order-to-capture association; the engine will not infer one
from coincidental values or amount matching. These are proposed interface
changes only and are not implemented as schema/model changes here.

## Reconciliation rules

| Exception type | Deterministic condition |
|---|---|
| `MISSING_PAYMENT` | An input merchant order has no payment record with the same merchant order ID. |
| `MISSING_ORDER` | A payment references a merchant order ID absent from the input orders. |
| `AMOUNT_MISMATCH` | Sum of successful captures in the order currency differs from the expected amount. |
| `CURRENCY_MISMATCH` | A recognized successful capture uses a currency different from the order currency. |
| `STATUS_MISMATCH` | A recognized paid order has a denied/failed capture and/or has no recognized successful capture; a payment with no capture ID is incomplete; or a capture timestamp falls outside the order-creation to detection-time window. |
| `REFUND_MISMATCH` | Merchant refund totals by currency differ from the supplied PayPal refund snapshot totals. |
| `DELAYED_UPDATE` | A webhook receipt is at least the configured threshold after event occurrence, or an old order with a recognized successful capture has no capture timestamp. |
| `DUPLICATE_WEBHOOK_DELIVERY` | The same PayPal event ID occurs more than once in supplied delivery records. It is not a duplicate-payment finding. |

Financial comparisons use `Decimal`. Float inputs are rejected for refund
calculations; the provisional DTO fields are typed as `Decimal`. Negative and
non-finite order/payment amounts and empty required IDs/currencies/statuses are
rejected as invalid input. Currency strings are trimmed and compared
case-insensitively. Amount mismatch is
calculated only when there is at least one successful capture in the expected
currency, avoiding a misleading zero-total mismatch when all captures have a
different currency or no recognized successful status.

### Provisional status assumptions

Member 1 has not confirmed lifecycle values. For standalone execution, the
default recognized values are:

- Paid order: `paid`, `completed`
- Successful capture: `completed`, `captured`
- Denied/failed capture: `denied`, `declined`, `failed`

These are configurable constructor inputs, not claims about the final database
enum or PayPal vocabulary. Unrecognized statuses are not silently treated as
successful. Exact production values require Member 1 confirmation.

## Severity and case identity

Severity is assigned by a fixed map in `rules.py`: amount, currency, missing
payment, and refund discrepancies are `HIGH`; missing order and status
discrepancies are `MEDIUM`; delayed updates and duplicate deliveries are `LOW`.
No finding is classified as fraud, and severity does not depend on an LLM.

Case IDs are stable SHA-256-derived identifiers based on exception type,
available record identifiers, expected/actual values, and evidence identifiers.
Detection time is recorded separately as an aware UTC timestamp. Evidence lists
contain only identifiers present in supplied records; absent IDs are not
fabricated. The `ExceptionManager` stores case statuses in memory only.

## Partial captures and event ordering

Multiple captures linked to one merchant order ID are grouped and their
successful amounts in the order currency are summed before comparing with the
order total. Capture IDs are checked for duplicate input records. Capture
records in other currencies generate currency exceptions and are excluded from
the order-currency sum.

Webhook delay is calculated from `occurred_at` to `received_at`; receipt order
does not determine lifecycle order. Duplicate delivery detection groups on the
PayPal event ID and never creates a payment record or treats the event as a
second financial transaction.

## Synthetic fixture limitations

`backend/tests/fixtures/synthetic_reconciliation.py` labels every record and
identifier as synthetic. These fixtures are local unit-test inputs only; they
are not real PayPal transactions, sandbox responses, verified webhook
deliveries, or a proposed production dataset. The refund mapping and status
values are test shapes pending the shared schema/API confirmation.

## Future integration with Member 1

After Member 1 confirms the schema and endpoints:

1. Map confirmed API/database records to the provisional DTOs or replace DTO
   fields with agreed interface types without duplicating SQLAlchemy models.
2. Confirm payment/capture ID mapping, status vocabularies, refund linkage,
   currency format, timestamp timezone semantics, and data-completeness
   guarantees.
3. Supply complete and consistently scoped order, payment, webhook, and refund
   snapshots to the pure engine.
4. Add API/service orchestration separately; keep persistence and HTTP concerns
   outside this engine.

Until then, database-dependent reconciliation and production severity/status
assumptions remain blocked on Member 1's confirmation.
