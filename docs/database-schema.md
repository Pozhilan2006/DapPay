# Database schema

The database layer is designed around event-driven financial reconciliation.
The first implemented persistence migration is
`backend/alembic/versions/20261111_01_paypal_persistence.py`.

## Implemented tables

### `merchant_orders`

Internal integer primary key; unique PayPal order ID; optional merchant
reference and invoice ID; nullable `NUMERIC(32, 12)` amount and 3-character
currency; intent and PayPal status; PayPal create/update timestamps; internal
created/updated timestamps.

Amounts can be nullable for externally received events that do not contain
order totals. Missing values are not synthesized.

### `payment_captures`

Internal integer primary key; unique PayPal capture ID; foreign key to the
PayPal order ID; capture status; nullable `NUMERIC(32, 12)` amount and currency;
`NUMERIC(32, 12)` refunded total; PayPal create/update timestamps; optional
compact source-event reference; internal created/updated timestamps.

Refund activity is aggregated on the capture record; individual refund records
are not separately persisted yet.

### `webhook_events`

Internal integer primary key; unique PayPal event ID; event/resource type and
resource ID; timezone-aware event occurrence and receipt timestamps;
verification and processing status; sanitized JSON payload; optional
processing error.

The stored event JSON omits payer/contact/payment-source details. Signature
verification uses the parsed incoming event before this storage sanitization.

## Migration and database URL

Alembic reads `DATABASE_URL` through application settings. Apply migrations
with:

```powershell
Set-Location F:\Recon\payrecon-ai\backend
python -m alembic upgrade head
```

The Docker Compose backend waits for PostgreSQL and applies `alembic upgrade
head` before starting Uvicorn. The provisional Member 2 DTOs remain separate
from these SQLAlchemy models; reconciliation and lineage consumers are not
wired to this schema.

## Planned, not implemented

- Merchant business records, fulfillment/shipping, and accounting entries
- Separate refund records
- Reconciliation runs, exceptions, investigations, and lineage edges
