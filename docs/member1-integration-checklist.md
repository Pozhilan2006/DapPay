# Member 1 integration checklist

Use this checklist to confirm the shared payment-data contract before Member 2
implements database-dependent logic. The repository currently has placeholder
routes and no payment-domain models or migrations.

## CONFIRMED

- One FastAPI application exists and mounts routes under `/api`.
- SQLAlchemy `Base` exists, but no payment, order, capture, webhook, refund, or
  merchant-business SQLAlchemy models are defined.
- Payment/order/webhook route functions currently return placeholder responses;
  they do not read persisted data.
- The proposed consumer fields and typed DTOs are documented in
  [`member2-data-contract.md`](./member2-data-contract.md) and
  [`backend/app/integration_contracts/payment_data.py`](../backend/app/integration_contracts/payment_data.py).

## PROPOSED

- Provide read access to merchant orders, PayPal payment/capture records, and
  webhook events through agreed API endpoints.
- Preserve `Decimal`/SQL `NUMERIC` amount semantics and the associated currency
  code.
- Expose event occurrence time separately from event receipt time.
- Keep merchant order ID, PayPal order ID, PayPal capture ID, and webhook event
  ID distinct.
- Treat duplicate webhook delivery separately from duplicate financial
  transactions.

## MISSING

- Actual payment-domain table and column definitions, migrations, keys,
  relationships, constraints, and timestamp semantics.
- Concrete Pydantic schemas and non-placeholder response payloads.
- Merchant order/payment/capture/webhook/refund lifecycle status values.
- Merchant fulfillment/shipping, accounting-entry, and refund sources and
  record schemas.
- Implemented webhook verification and a defined raw-payload retention policy.
- Implemented endpoint authentication, pagination, filtering, and error formats.

## REQUIRES MEMBER 1 CONFIRMATION

1. What are the final database table names?
2. What are the final primary and foreign keys?
3. What are the exact payment and order status values?
4. How is the merchant order ID linked to a PayPal order and capture?
5. What is the normalized webhook JSON structure?
6. How are webhook signatures verified?
7. Are raw webhook payloads preserved?
8. What API endpoints can Member 2 consume?
9. What are the API response formats?
10. How are refunds and partial captures represented?

Also confirm the exact field names, nullability, currency representation, and
timestamp timezone rules for the proposed fields in the data-contract document.
Member 2 should wait for these answers and a shared schema/API confirmation
before adding persistence or reconciliation logic.
