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
| `MISSING_PAYMENT` | A paid merchant order has no payment record, an unpaid order has no payment after the configured threshold, or a related capture is denied after that threshold. |
| `MISSING_ORDER` | A payment references a merchant order ID absent from the input orders. |
| `AMOUNT_MISMATCH` | Sum of successful captures in the order currency differs from the expected amount. |
| `CURRENCY_MISMATCH` | A recognized successful capture uses a currency different from the order currency. |
| `STATUS_MISMATCH` | Merchant and PayPal snapshot statuses conflict, a paid order lacks a successful capture, full successful capture totals are not reflected as paid by the merchant after the threshold, the latest verified capture event conflicts with merchant status, a payment has no capture ID, or a capture timestamp falls outside the order-creation to detection-time window. |
| `REFUND_MISMATCH` | Merchant refund totals by currency differ from the supplied PayPal refund snapshot totals. |
| `MISSING_ACCOUNTING_ENTRY` | A PayPal refund has no merchant accounting entry referencing the refund ID, or the original capture plus exact amount and currency. |
| `DELAYED_UPDATE` | A webhook receipt is at least the configured threshold after event occurrence, a pending capture remains unresolved after the threshold, or an old successful capture has no capture timestamp. |
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

### Task 4 requirement coverage

| Requirement | Coverage | Implementation and evidence |
|---|---|---|
| Amount mismatch identifies both systems and calculates the difference | Covered | `AMOUNT_MISMATCH` retains merchant/order/capture evidence, compares Decimal totals, and states the signed actual-minus-expected difference. `test_amount_mismatch_uses_decimal_total` verifies values and delta. |
| Missing payment distinguishes pending from failed/missing and avoids premature classification | Covered with threshold | Recent unpaid orders are left pending; stale unpaid orders without a payment become `MISSING_PAYMENT`; pending captures become `DELAYED_UPDATE`; denied captures become `MISSING_PAYMENT` only after the configured threshold. Paid orders with no payment remain an immediate discrepancy. |
| Status mismatch uses latest relevant events and catches missing merchant updates | Partial | Snapshot comparison handles completed/denied states. Full successful capture totals not reflected as paid are flagged after the threshold. For verified capture webhook events, the latest event is selected by occurrence time (not receipt time) and its ID is attached as evidence. Only `PAYMENT.CAPTURE.PENDING`, `.COMPLETED`, and `.DENIED` are interpreted. The DTO has no merchant status-update timestamp or event history, so a missing update is inferred using order age, not proven from an update timestamp. |
| Refund links to original capture and detects missing accounting entries | Partial | Refund capture IDs must resolve to a known capture; an order-only link is accepted only when that order has exactly one capture. Totals remain Decimal/currency-based. Missing accounting is detected using a refund ID (`paypal_refund_id`, `refund_id`, or `reference_id`) or a capture ID plus exact amount/currency. Member 1 must confirm these accounting field conventions. |
| Duplicate webhook delivery differs from a separate transaction | Covered | Duplicate findings group on repeated PayPal event ID and do not create payment records. Separate event IDs do not trigger duplicate-delivery findings. |
| Deterministic rule-based detection and stable case identifiers | Covered | Rules are explicit and use stable SHA-256 case identities independent of detection time; event selection orders by occurrence time and event ID for ties. |
| Event sequence validation | Partial | The latest verified capture state is selected by `occurred_at`; late receipt of an older event cannot overwrite it. Sequence interpretation is limited to the supported capture event types and completeness of the supplied event snapshot. |
| Cross-system status comparison and missing relationships | Partial | Orders/payments match on merchant order ID; unmatched payments produce `MISSING_ORDER`; capture/refund relationships are validated. The provisional webhook DTO has only one related resource ID, so unrelated or unmapped webhook resources are not assigned an order by guesswork. |
| Decimal-safe comparison and configurable time thresholds | Covered | Monetary fields use `Decimal`; the engine's `delay_threshold` controls missing/pending payment and update timing. |
| Partial/multiple captures, delayed webhooks, repeated delivery, refunds | Covered by unit tests | Multiple capture totals are summed; refund links on multi-capture orders require an explicit capture ID; webhook delay uses occurrence/receipt times; duplicate IDs and refund accounting are separately tested. |

## Severity and case identity

Severity is assigned by a fixed map in `rules.py`: amount, currency, missing
payment, refund, and missing-accounting-entry discrepancies are `HIGH`; missing
order and status discrepancies are `MEDIUM`; delayed updates and duplicate
deliveries are `LOW`.
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
the order-currency sum. A completed full total with an unpaid merchant status
is reported after the update threshold; an incomplete partial total is not
classified as a missing merchant paid update.

Webhook delay is calculated from `occurred_at` to `received_at`; receipt order
does not determine lifecycle order. Verified capture status events are grouped
by related capture ID and the event with the latest occurrence time is used for
status comparison. Duplicate delivery detection groups on the PayPal event ID
and never creates a payment record or treats the event as a second financial
transaction. Event-based status reconciliation only trusts verification
statuses `SUCCESS` and `verified`.

## Synthetic fixture limitations

`backend/tests/fixtures/synthetic_reconciliation.py` labels every record and
identifier as synthetic. These fixtures are local unit-test inputs only; they
are not real PayPal transactions, sandbox responses, verified webhook
deliveries, or a proposed production dataset. The refund mapping and status
values are test shapes pending the shared schema/API confirmation. Accounting
entry linkage is provisional and must be aligned with the actual ledger
contract before this rule is used against production data.

## Future integration with Member 1

After Member 1 confirms the schema and endpoints:

1. Map confirmed API/database records to the provisional DTOs or replace DTO
   fields with agreed interface types without duplicating SQLAlchemy models.
2. Confirm payment/capture ID mapping, status vocabularies, refund linkage,
   accounting-entry reference fields, currency format, timestamp timezone
   semantics, merchant status-update timestamps, and data-completeness
   guarantees.
3. Supply complete and consistently scoped order, payment, webhook, and refund
   snapshots to the pure engine.
4. Add API/service orchestration separately; keep persistence and HTTP concerns
   outside this engine.

Until then, database-dependent reconciliation and production severity/status
assumptions remain blocked on Member 1's confirmation.
