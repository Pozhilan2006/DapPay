# Payments API contract

The frontend uses only existing FastAPI endpoints:

- `GET /api/payments?limit={limit}&offset={offset}` returns a JSON array of capture responses. `limit` is 1–100 (default 50) and `offset` is 0 or greater. The frontend requests 25 records per page. The API does not return a total count and does not support search, status, or date filters.
- `GET /api/payments/{payment_id}` looks up a capture by its PayPal capture ID and returns the same response shape.
- `GET /api/orders?limit={limit}&offset={offset}` returns a JSON array of merchant orders with the same pagination bounds.
- `GET /api/orders/{order_id}` looks up an order by PayPal order ID. Payment rows use this endpoint to display merchant references; selected payment details reload the capture and related order independently.
- `GET /api/reconciliation` reports readiness only; it does not return reconciliation results or exception cases.
- `GET /api/webhooks?limit={limit}&offset={offset}` lists verified webhook summaries. This endpoint is not used by the dashboard overview.
- Investigation report reads are case/report-specific (`GET /api/investigations/{case_id}`, `/api/investigations/{case_id}/reports`, and `/api/investigations/reports/{report_id}`); there is no global investigation or exception list endpoint.

The overview requests up to 100 captures and labels this as the current API page, not a merchant-wide total. Completed, pending, and failed/denied/declined counts are derived from those returned records only. Its activity chart groups only returned captures with valid PayPal timestamps by date and preserves each status value; with fewer than two dated groups it shows a recent-captures table instead. Reconciliation match rate, exception count, active investigation count, and discrepancy amount are shown as unavailable because the backend has no suitable read/list contract for them. Discrepancy totals are not inferred from payments.

Payment responses contain `payment_id`, `order_id`, `status`, `amount`, `refunded_amount`, `currency`, `paypal_created_at`, and `paypal_updated_at`. Order responses contain `order_id`, `merchant_reference`, `invoice_id`, `amount`, `currency`, `intent`, `status`, PayPal timestamps, and database `created_at`/`updated_at` timestamps. Amount fields originate in PostgreSQL `Numeric` columns and Pydantic serializes them as JSON strings; the API client keeps them as strings and never converts them to JavaScript numbers. Timestamps are timezone-aware ISO strings. The UI formats them only after validating the date.

Protected API routes require a bearer JWT with `exp`, `iat`, `iss`, `aud`, `sub`, and `role`. Accepted roles are `admin`, `merchant`, and `read_only`. Non-admin tokens must include a non-empty `merchant_id` (maximum 128 characters); their reads are scoped to that merchant. Admin reads are unscoped. The verifier currently accepts HS256 only and validates `iss` and `aud` against backend configuration. FastAPI errors use `{"detail": "..."}`. Missing/invalid/expired tokens return 401 with `WWW-Authenticate: Bearer`; insufficient roles return 403; missing records return 404; storage failures return 503.

The backend verifies HS256 tokens using its private `AUTH_JWT_SECRET`; the frontend never receives or stores that signing secret and never creates tokens. A production identity provider must issue short-lived bearer tokens with the required claims, matching issuer/audience, one of the accepted roles, and a merchant ID for non-admin users. The secret must remain only in trusted backend/identity-provider configuration. If the chosen provider signs with RS256/JWKS instead, backend verification support must be added before connecting it; the frontend must not compensate by signing tokens. `configureAccessTokenProvider` is the integration seam for a trusted identity provider to supply access tokens. No real identity-provider token provider is currently wired into this app, so authenticated live payment access remains blocked until that integration is supplied. With no provider, the frontend makes the read request without authorization and displays the backend's 401 state; it does not substitute demo rows.

### Identity-provider readiness

The verifier requires these exact claims:

| Claim | Requirement |
|---|---|
| `iss` | Exact match for `AUTH_JWT_ISSUER` |
| `aud` | Contains/matches `AUTH_JWT_AUDIENCE` |
| `sub` | Non-empty stable identity-provider subject |
| `role` | `admin`, `merchant`, or `read_only` |
| `iat` | Issued-at timestamp |
| `exp` | Expiration timestamp; expired tokens are rejected |
| `merchant_id` | Required for `merchant` and `read_only`; non-empty, at most 128 characters |

The backend currently pins PyJWT verification to **HS256**, using the shared
`AUTH_JWT_SECRET`, and validates issuer, audience, required claims, token
expiration, role, and tenant claim. It does not discover OIDC metadata, fetch
JWKS keys, or validate an asymmetric signature. Common OIDC providers issue
RS256-signed access tokens, so their tokens fail this backend's HS256-only
verification. Do not configure an OIDC provider to share an HS256 secret or
weaken verification merely to connect it.

Before using an RS256/JWKS provider, backend work must add a verifier that:

1. Loads OIDC discovery metadata only from a configured, trusted issuer over
   HTTPS and restricts the configured API audience.
2. Selects a public key by JWT `kid` from the issuer's JWKS endpoint, caches
   keys safely, refreshes on key rotation/unknown `kid`, and rejects unknown
   algorithms or keys.
3. Verifies signature, exact issuer, API audience, `exp`, `nbf` when present,
   and required identity/authorization claims; validates claim types and maps
   provider role/permission claims explicitly to PayRecon's roles.
4. Fails closed on invalid issuer metadata, key fetch/refresh failure, or
   invalid tokens, without logging tokens or authorization headers.

Recommended architecture: use a trusted OIDC provider with Authorization Code
flow and PKCE. Prefer a same-origin backend-for-frontend (BFF) for this
financial UI: the BFF keeps tokens server-side and gives the browser a
`Secure`, `HttpOnly`, `SameSite` session cookie with CSRF protection. If the
browser calls this API directly, use the provider's maintained SPA SDK and
short-lived API access tokens; never embed a client secret or signing key in
Next.js. Wire the SDK's in-memory token getter into
`configureAccessTokenProvider`; it must return an access token for this API's
audience and must rely on the SDK's silent renewal/reauth flow, not generate
or edit JWT claims. That seam exists, but no provider currently calls it.

The issuer must put a trusted role and tenant entitlement in the signed token,
or the backend must map the stable `sub` to current entitlements through a
trusted server-side directory. `merchant_id` must be PayRecon's stable,
opaque tenant key, assigned during merchant onboarding and mapped to the
merchant's PayRecon account; it must not come from a request parameter or an
unverified merchant reference. Admins may omit it. Use short access-token
lifetimes (typically 5–15 minutes); the provider SDK/BFF should renew silently
before expiry and handle renewal failure by returning to sign-in. Do not keep
long-lived refresh tokens in browser local storage. Revocation and role/tenant
changes must have a defined propagation strategy.

The backend allows CORS only for configured origins. Development defaults to
`http://localhost:3000` and `http://127.0.0.1:3000`. Staging and production
must set `CORS_ALLOWED_ORIGINS` to a JSON array of approved HTTPS origins, for
example `["https://payments.example.com"]`. Wildcard origins, paths, and
non-HTTPS origins outside development are rejected. The allowed request
headers include `Authorization`, `Content-Type`, and `Accept`; allowed methods
are GET and POST. CORS is not authentication and does not replace JWT or
merchant-ownership checks.

Search and status filtering operate only on the currently loaded API page. Status choices come from values returned on that page. Next/previous use the backend's `limit`/`offset`; because the API does not report totals, the UI reports the current page and does not claim a database-wide total. Order references are retrieved by detail endpoint in batches of five requests; a missing order (404) is shown as unavailable while other API failures are surfaced.

`NEXT_PUBLIC_API_BASE_URL` is the only frontend API address configuration. The existing example value targets `http://localhost:8000` for local development. `NEXT_PUBLIC_PAYPAL_MODE` controls only the visible Sandbox label and must match backend `PAYPAL_MODE`; it does not select or change the backend's PayPal environment. The overview and Payments page use API responses only; authentication or API failures show unavailable states and never substitute sample figures. Reconciliation, investigation, lineage, and settings views are explicitly unavailable until suitable backend read APIs and authenticated identity data are connected. The frontend does not contain a token provider; until a trusted provider calls `configureAccessTokenProvider`, protected requests return the backend's 401 state. No backend payment, reconciliation, investigation, or webhook behavior was changed for this integration; CORS is configured separately through `CORS_ALLOWED_ORIGINS`.
