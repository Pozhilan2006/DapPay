# API authentication and tenant authorization

## Authentication model

PayRecon verifies externally issued, short-lived JWT access tokens. It does not
provide a login endpoint, store user passwords, create users, or issue tokens.
Tokens must use **HS256** and contain:

- `iss`: configured `AUTH_JWT_ISSUER`
- `aud`: configured `AUTH_JWT_AUDIENCE`
- `sub`: stable identity-provider subject
- `role`: `admin`, `merchant`, or `read_only`
- `iat` and `exp`
- `merchant_id` for `merchant` and `read_only` roles

Every protected request sends `Authorization: Bearer <JWT>`. Missing or invalid
tokens receive `401`; insufficient role receives `403`. Authentication fails
closed with `503` if `AUTH_JWT_SECRET` is unset or shorter than 32 bytes.
There is no development bypass.

Configure these values in the backend environment:

```dotenv
AUTH_JWT_SECRET=<random secret of at least 32 bytes>
AUTH_JWT_ISSUER=<trusted identity-provider issuer>
AUTH_JWT_AUDIENCE=payrecon-api
```

Generate a secret locally with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do not commit the generated secret. Store it in the deployment secret manager
and configure the trusted token issuer with the same signing secret. Rotate it
by coordinating issuer and API configuration; rotation invalidates all tokens
signed with the prior value. Prefer short token lifetimes. TLS is required
between clients, the identity provider, and the API.

## Onboarding and ownership

An operator provisions user identities and roles in the trusted identity
provider. Merchant onboarding assigns a stable, opaque `merchant_id` and binds
that tenant to the merchant's PayRecon account outside this API. The issuer
puts the assigned tenant ID and role in each token. PayRecon trusts only these
signed claims; clients cannot choose a tenant with a request parameter.

New orders created by a merchant token are stored with that token's
`merchant_id`. PayPal webhook ingestion continues to use PayPal's official
signature verification independently; a webhook does not need an application
user token. Webhook event reads are scoped through their persisted order or
capture. Events with no tenant-linked order/capture are visible only to an
administrator.

Migration `20261111_03` adds nullable tenant ownership to orders and
reconciliation cases. Existing rows are intentionally left unowned because the
database has no reliable tenant mapping. They are hidden from tenant tokens and
remain administrator-only until an operator verifies ownership and performs a
controlled backfill. Do not assign tenants based only on an untrusted
merchant reference.

## Authorization matrix

| Resource/action | Administrator | Merchant | Read-only |
|---|---:|---:|---:|
| Orders, captures, PayPal order retrieval | All tenants | Own tenant | Own tenant |
| Create/capture PayPal order | Yes | Own tenant | No |
| Webhook event list/detail | All | Own tenant | Own tenant |
| PayPal webhook POST | PayPal signature only | PayPal signature only | PayPal signature only |
| Reconciliation status/run | All | Own tenant | Status only |
| Transaction review | All | Own tenant | Own tenant |
| Investigation validate/report reads | All | Own tenant | Own tenant |
| Investigation run | All | Own tenant | No |

Health remains public and returns service status only. The lineage placeholder
requires an authenticated token.

## Operational limitations

- The application has no identity-provider integration, user directory,
  password recovery, account lifecycle, or token issuance endpoint. Those
  responsibilities must be provided by the operator's identity provider.
- HS256 requires the identity provider and API to share a high-entropy secret.
  Keep it in a secrets manager and restrict access; use an asymmetric/JWKS
  verification integration before adopting an issuer that cannot safely share
  this key.
- Legacy unowned records are administrator-only until ownership is verified and
  backfilled.
- Application auth does not replace TLS, network controls, rate limiting,
  secret rotation, audit monitoring, or PayPal webhook signature verification.
- Protect public deployment behind TLS and the intended network boundary; do
  not expose the API until secrets, issuer, audience, tenant onboarding, and
  legacy ownership mapping are configured and verified.
