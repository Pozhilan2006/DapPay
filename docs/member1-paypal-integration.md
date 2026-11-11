# Member 1 PayPal integration

This document describes the backend's PayPal Orders v2 and webhook foundation.
The webhook API follows PayPal's
[webhook signature verification reference](https://developer.paypal.com/docs/api/webhooks/v1/#verify-webhook-signature)
and the official
[PayPal REST API specification](https://github.com/paypal/paypal-rest-api-specifications/blob/main/openapi/notifications_webhooks_v1.json).

## Environment

Copy `backend/.env.example` to `backend/.env` and set values locally:

| Variable | Purpose |
|---|---|
| `PAYPAL_MODE` | `sandbox` or `live`; identifies the configured environment. |
| `PAYPAL_CLIENT_ID` | PayPal REST app client ID. |
| `PAYPAL_CLIENT_SECRET` | PayPal REST app secret. |
| `PAYPAL_BASE_URL` | Sandbox `https://api-m.sandbox.paypal.com` or Live `https://api-m.paypal.com`. |
| `PAYPAL_WEBHOOK_ID` | Webhook ID from the same PayPal REST app and environment. Leave empty until registered. |
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL using the `psycopg` driver. |
| `SECRET_KEY` | Existing application secret; keep its local value. |

Never put live credentials in `.env.example`, source control, or logs. `.env` is
ignored by Git. The webhook verification route returns a configuration error
when the webhook ID or REST app credentials are missing.

## PostgreSQL

From PowerShell at the repository root, set a local PostgreSQL password without
echoing it (use URL-safe letters, digits, `_`, or `-` for the Compose-generated
connection URL) and start the database and backend:

```powershell
$secure = Read-Host "Local PostgreSQL password" -AsSecureString
$env:POSTGRES_PASSWORD = [System.Net.NetworkCredential]::new("", $secure).Password
docker compose up -d db backend
docker compose ps
docker compose logs backend
```

The backend waits for PostgreSQL's health check, constructs its container
`DATABASE_URL` from the Compose environment, and runs migrations before Uvicorn.
For manual migration or inspection:

```powershell
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

For a local Python process, set `DATABASE_URL` in `backend/.env` to the host
PostgreSQL URL and run from `backend`:

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Do not switch the application to SQLite to recover from PostgreSQL connection
failures. SQLite is used only by isolated unit tests. The checked-in schema is
the initial migration `20261111_01`; it creates `merchant_orders`,
`payment_captures`, and `webhook_events`.

## Register a webhook

1. In the PayPal Developer Dashboard, select the REST app matching
   `PAYPAL_MODE` and `PAYPAL_BASE_URL`.
2. Register the public HTTPS listener URL:
   `https://<your-public-host>/api/webhooks/paypal`.
3. Subscribe at least to:
   `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.PENDING`,
   `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, and
   `PAYMENT.CAPTURE.REFUNDED`.
4. Copy the webhook ID from that app into local `PAYPAL_WEBHOOK_ID`.
5. Restart the backend so settings reload.

PayPal must be able to reach the endpoint over public HTTPS. A local
`localhost` URL is not a production webhook destination. Configure an HTTPS
reverse proxy and firewall limits before exposing the service. Webhook
registration is performed in the Developer Dashboard; this backend does not
create webhook registrations automatically.

## Verification and ingestion

`POST /api/webhooks/paypal` reads the incoming event JSON and the five
`PAYPAL-*` transmission headers, then calls PayPal's
`POST /v1/notifications/verify-webhook-signature` API with those headers,
the configured webhook ID, and the event. Only PayPal's
`verification_status: SUCCESS` proceeds to storage. A missing webhook ID fails
closed; unsigned, malformed, or failed-verification requests are rejected.
The application does not fetch a caller-supplied certificate URL.

Verified event insertion, domain synchronization, and processing status commit
in one database transaction. A PayPal event ID unique constraint prevents
double processing. Repeated verified deliveries receive HTTP 200 with
`{"status":"duplicate","duplicate":true}`. If database or authoritative PayPal
lookups fail, the transaction rolls back and the endpoint returns a retryable
error. The event occurrence timestamp and server receipt timestamp are stored
separately in UTC.

Raw events are retained as JSON after removing personal/contact and credential
fields (including payer, email, address, phone, card, and payment-source
objects). The unmodified parsed event is used for signature verification
before this storage sanitization. Do not treat simulator payloads or a
successful HTTP response by themselves as genuine deliveries.

Capture-completed notifications are not accepted as proof of completed payment
on their own. The service retrieves the PayPal order and requires the matching
capture to be present in PayPal's current order response before persisting its
authoritative capture status. The event transaction is retried if that lookup
cannot confirm the capture. Capture statuses are monotonic: late pending or
denied notifications do not downgrade a completed capture. Refund totals are
aggregated on the capture record; partial refunds do not change the capture's
completed status, while a refund total at least equal to the captured amount
marks it `REFUNDED`.

## Stored records and APIs

- `merchant_orders`: unique PayPal order ID, merchant/invoice references,
  Decimal amount/currency, intent/status, PayPal timestamps, and internal
  created/updated timestamps.
- `payment_captures`: unique capture ID, order relationship, status, Decimal
  captured/refunded amounts, currency, PayPal timestamps, and a compact source
  event reference.
- `webhook_events`: unique PayPal event ID, event/resource metadata, separate
  occurrence/receipt times, verification/processing state, sanitized original
  JSON, and optional processing error.

Read endpoints:

- `GET /api/orders?limit=50&offset=0` and `GET /api/orders/{paypal_order_id}`
- `GET /api/payments?limit=50&offset=0` and
  `GET /api/payments/{paypal_capture_id}`
- `GET /api/webhooks?limit=50&offset=0` and
  `GET /api/webhooks/{paypal_event_id}`

The detail webhook endpoint returns the sanitized payload. These read APIs
currently have no application authentication layer; put them behind a trusted
authenticated gateway before exposing transaction data publicly.

## Local API and test instructions

With the backend running, use the create/approve/capture flow:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/paypal/orders `
  -ContentType application/json `
  -Body '{"amount":"25.50","currency":"USD","merchant_reference":"local-order-1","return_url":"https://merchant.example/return","cancel_url":"https://merchant.example/cancel"}'
```

PayPal redirects the buyer to the returned approval URL. Only after approval
should the capture endpoint be called. An order-created or approved status is
not payment confirmation.

Run backend tests from `backend`:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
```

Tests use mocked PayPal responses and an isolated in-memory SQLite database;
they are not real PayPal webhook deliveries. Run
`python -m alembic upgrade head` against PostgreSQL for database integration.

## Known limitations

- Webhook registration is manual; no webhook-management endpoint is provided.
- No periodic recovery/reconciliation worker is implemented for events that
  repeatedly fail authoritative lookups.
- Refunds are aggregated on captures; individual refund records are not a
  separate table.
- These read APIs are unauthenticated and must not be exposed publicly without
  an authenticated gateway.
- No actual webhook delivery is claimed by mocked tests.
