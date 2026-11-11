# AI root-cause investigation

## Status and scope

The backend has a bounded, evidence-grounded investigation workflow built on
the current PayPal persistence models. The pure reconciliation engine still
accepts provisional DTOs, while `run_persisted_reconciliation()` converts the
persisted PayPal orders, captures, and verified webhooks into those DTOs and
persists only the resulting genuine exception cases. Stable engine case IDs are
the persistence primary keys, making repeat runs idempotent.

The investigation service never performs payment operations or changes a
payment, order, refund, accounting record, or exception status. Reports are
append-only snapshots and always require human approval for any consequential
follow-up.

## Existing implementation assessment

Before this work, `app/ai_investigation/` contained placeholder functions for
evidence retrieval, response schema, validation, and queued investigation.
The investigations API exposed placeholder routes. The repository already had:

- PayPal order, capture, and webhook SQLAlchemy models and persistence.
- A deterministic reconciliation engine and stable in-memory exception IDs.
- A NetworkX lineage builder with explicit-ID relationships.
- A generic event timeline scaffold.
- No persisted reconciliation-case model, investigation report model, LLM
  provider manager, merchant-side order table, refund table, accounting table,
  fulfillment table, or investigation-specific tests.

The LLM/provider implementation is therefore a small Ollama HTTP adapter using
the existing `httpx` dependency, not a second general-purpose provider
framework. No provider credentials are configured or required by unit tests.

## Architecture and workflow

`POST /api/reconciliation/run` is the production integration boundary. It
commits the reconciliation cases in the same database transaction after the
engine has returned them; a successful normal payment therefore produces no
case. `POST /api/investigations/reviews/orders/{paypal_order_id}` is a separate,
read-only completed-payment verification. It never creates a case or report,
and does not invoke the LLM. Exception investigations remain available at
`/api/investigations/{case_id}/run`, with evidence validation and append-only
report history under that case.

1. A persisted reconciliation case ID is validated.
2. The evidence collector queries only PayPal order/capture IDs and exact
   merchant-reference matches recorded on that case.
3. Persisted webhook events are retrieved only when their resource ID matches
   one of those order/capture IDs.
4. Sensitive fields are excluded; only a small allowlist from webhook resource
   data is retained. The full raw payload is not sent to the model.
5. Evidence IDs are deterministic hashes of source system, record type, and
   original record ID. The original source IDs and source system remain in the
   snapshot.
6. The timeline orders by occurrence time. Receipt time is retained separately
   and is used only as explicitly marked fallback ordering where occurrence
   time is absent.
7. The existing `LineageGraphBuilder` constructs an in-memory NetworkX graph.
   Missing relationship endpoints and disconnected graph nodes are included
   in the evidence snapshot.
8. Deterministic analysis performs Decimal-based arithmetic and timestamp/
   status checks before any model call.
9. A configured Ollama model receives the sanitized evidence snapshot,
   deterministic analysis, case metadata, and a strict JSON schema. The prompt
   treats all record values as untrusted data and provides no tools.
10. Pydantic validates the model response. Evidence IDs, case ID, issue type,
    and severity are then checked against the exact current snapshot.
11. A bounded retry (at most two model calls) is allowed after a provider or
    evidence-reference validation error.
12. A successful or failed attempt is appended as an immutable report record.
    Earlier reports are not overwritten.

The model may provide only a tentative probable-cause hypothesis, qualitative
confidence, confidence basis, and recommended human action. Financial facts
and deterministic findings are produced by backend code.

## Evidence and timeline

Evidence items retain `evidence_id`, `source_system`, `record_type`,
`source_record_id`, related IDs, occurrence and receipt timestamps, webhook
processing/verification status, and a sanitized data subset.

The current collector can retrieve:

- Persisted reconciliation case values.
- PayPal order status, amount, currency, intent, invoice/reference IDs, and
  PayPal timestamps.
- All currently persisted captures associated by PayPal order ID, including
  Decimal amount, currency, status, timestamps, and accumulated refunded
  amount.
- Persisted webhook event IDs/types, resource IDs, occurrence/receipt times,
  and verification/processing status.

Evidence collection is bounded to 200 related records per source. A truncated
snapshot is explicitly marked incomplete. Duplicate delivery attempts are
not separately persisted by the current webhook schema, so the engine cannot
reconstruct delivery counts from the unique-event table.

The timeline preserves `occurred_at` and `received_at` as distinct values.
Items lacking both timestamps are marked as having unavailable ordering time.

## Lineage

The existing graph builder is reused without connecting records by amount or
time proximity. Edges require explicit IDs. The snapshot reports disconnected
nodes, unresolved endpoints, and ambiguous references. Because there is no
independent merchant order source, the persisted PayPal `MerchantOrder` model
is never mislabeled as a merchant-side order. Its exact merchant reference
can be used as an explicit association reference, but not as independent
merchant-side evidence.

Refund, accounting, fulfillment, and merchant status-update records are not
stored in the current database schema. Their data sources are reported as
unavailable; records and IDs are not fabricated. A PayPal capture's persisted
aggregate `refunded_amount` is reported only as an aggregate, not as a
refund-level record.

## Deterministic analysis

All amounts used in calculation are parsed into `Decimal`; binary-float
amounts are rejected as inputs to the analysis. The engine reports:

- Recorded reconciliation expected/actual values and their signed difference
  when both values are valid decimal scalars.
- Persisted PayPal capture totals by currency.
- PayPal order amount versus persisted capture-total observations, without
  classifying a partial capture or incomplete snapshot as an anomaly.
- Persisted aggregate refunded totals when present.
- Capture/webhook status conflicts by explicit capture ID and latest verified
  event occurrence time.
- Capture timestamps that precede an available approval event, delayed
  webhook receipts, and delayed pending capture confirmations.
- Payment state as pending, completed, failed, missing, conflicting, or
  unknown. Missing data alone is not treated as a failed payment.

Thresholds are configurable using:

- `INVESTIGATION_MISSING_PAYMENT_MINUTES`
- `INVESTIGATION_WEBHOOK_DELAY_MINUTES`
- `INVESTIGATION_MERCHANT_UPDATE_MINUTES`
- `INVESTIGATION_CAPTURE_CONFIRMATION_MINUTES`
- `INVESTIGATION_ACCOUNTING_DELAY_MINUTES`

Merchant-update and accounting thresholds are recorded in the deterministic
analysis but cannot be evaluated against tables that do not yet exist.

## Schemas and validation

`InvestigationReport` uses categorical confidence (`LOW`, `MEDIUM`, `HIGH`),
with a required confidence basis stating that this assessment is not
calibrated. Every fact and deterministic conclusion requires evidence IDs.
LLM hypotheses must cite IDs from the current snapshot. Unknown IDs, case ID
changes, and changes to the persisted issue type or severity are rejected.

The response validator does not claim general natural-language entailment
checking. To reduce that risk, the model cannot author factual findings; its
only explanation field is stored as a `HYPOTHESIS`, never as a verified fact.

## LLM configuration

Configure the backend environment (or an isolated local Ollama installation)
with:

```dotenv
INVESTIGATION_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<installed-model-name>
INVESTIGATION_LLM_TIMEOUT_SECONDS=30
```

No client secret, PayPal access token, authorization header, raw card data, or
full webhook payload is included in the model request. The provider sends
structured JSON-schema output via Ollama's `/api/chat` endpoint. Provider
errors are sanitized, and no response text or transaction payload is logged.
Install and start Ollama and pull a model separately; no model is bundled.

## Persistence and migration

Migration `20261111_02` adds:

- `reconciliation_exception_cases`: stable case ID, exception type/severity,
  IDs, expected/actual values, evidence identifiers, status, and detection
  timestamp.
- `investigation_reports`: append-only report content, evidence snapshot,
  deterministic analysis, confidence basis, recommendation, provider/model/
  prompt metadata, validation errors, investigation time, and audit timestamps.

JSON uses PostgreSQL JSONB and a portable SQLAlchemy JSON variant for tests.
The case table is a persistence boundary only. The current reconciliation
route is still a placeholder, and the pure reconciliation engine does not
write cases. An upstream reconciliation orchestration must call
`persist_exception_cases(session, result.exception_cases)` in the same
appropriate transaction before the investigation API can find those cases.

Apply migrations from `backend/`:

```powershell
alembic upgrade head
```

The migration does not add refund, accounting, fulfillment, merchant-order,
or status-update tables.

## API

All routes are under `/api/investigations`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/{case_id}/run` | Collect, analyze, call model, validate, and append a report. |
| `POST` | `/{case_id}/validate` | Run collection and deterministic validation without an LLM call. |
| `GET` | `/{case_id}` | Retrieve latest saved report. |
| `GET` | `/{case_id}/reports` | Retrieve paginated report history. |
| `GET` | `/reports/{report_id}` | Retrieve a specific report. |

Example request (replace the illustrative case ID with a persisted case):

```http
POST /api/investigations/recon_0123456789abcdef0123/run
```

Example response shape (all values are illustrative, not transaction data):

```json
{
  "report_id": "00000000-0000-4000-8000-000000000001",
  "case_id": "recon_0123456789abcdef0123",
  "issue_type": "AMOUNT_MISMATCH",
  "severity": "HIGH",
  "investigation_status": "INCONCLUSIVE",
  "probable_cause": null,
  "findings": [
    {
      "finding_id": "FACT-CASE",
      "claim": "Recorded exception type is AMOUNT_MISMATCH.",
      "finding_type": "FACT",
      "evidence_ids": ["EVD-illustrative"],
      "explanation": "This fact describes the persisted reconciliation case."
    }
  ],
  "missing_evidence": ["Merchant source orders source is not implemented."],
  "conflicting_evidence": [],
  "confidence": "LOW",
  "confidence_basis": "Evidence is incomplete; confidence is qualitative and not calibrated.",
  "recommended_action": "Verify authoritative PayPal and merchant records.",
  "requires_human_approval": true,
  "investigated_at": "2026-11-11T12:00:00Z",
  "model_metadata": {
    "provider": "ollama",
    "model": "configured-local-model",
    "prompt_version": "1.0"
  }
}
```

Unknown cases return `404`; unavailable providers return `503` after a failed
attempt is persisted; invalid model evidence returns `502` after bounded
retries and failed-attempt persistence; database errors return a sanitized
`503`.

## Security and access control

No application authentication/authorization middleware exists in the inspected
backend. These financial investigation routes must remain behind a trusted,
authenticated development environment or secure gateway until authorization
is implemented. This code does not treat the placeholder `verify_api_token`
helper as authentication. Do not expose the routes publicly.

Investigation output is read-only. Recommendations are not actions and never
automatically capture, refund, update, create accounting records, or resolve
cases. Evidence and reports exclude unnecessary payer information. No raw
database errors or LLM response bodies are returned to clients.

## Testing

Investigation unit tests use SQLite and mocked provider responses. They cover
stable evidence IDs, source-field redaction, graph/timeline construction,
Decimal analysis, partial captures, out-of-order events, invalid evidence
references, prompt-injection isolation, provider errors, bounded retries,
append-only persistence, and API retrieval. They do not make real PayPal or
Ollama calls.

## Known limitations and requirement coverage

| Requirement area | Status | Notes |
|---|---|---|
| Evidence collection and stable snapshot IDs | PARTIALLY COMPLETE | PayPal-persisted records and cases are collected; independent merchant, refund, accounting, fulfillment, and merchant-update sources are unavailable. |
| Timeline timestamps and ordering | COMPLETE for collected sources | Occurrence and receipt times remain separate; no missing timestamp is fabricated. |
| Existing NetworkX lineage integration | PARTIALLY COMPLETE | The builder is reused and its missing links are preserved; merchant-side nodes and unsupported source types cannot be produced. |
| Deterministic Decimal/status analysis | PARTIALLY COMPLETE | Covers persisted case, PayPal order/capture, and webhook observations. Merchant-versus-PayPal comparisons require merchant source records. |
| Structured LLM output and bounded retries | PARTIALLY COMPLETE | Ollama is the only supported adapter because no prior provider manager exists. Model availability and behavior must be configured and verified locally. |
| Evidence reference validation | PARTIALLY COMPLETE | Case/classification/evidence IDs are checked; generic semantic entailment is not available. Model-generated explanations are always hypotheses. |
| Persistent cases and report history | PARTIALLY COMPLETE | Tables, migration, and case-writing helper exist. The reconciliation route does not yet invoke the helper. |
| Investigation API | PARTIALLY COMPLETE | Routes are implemented, but no auth exists and no current API creates/persists reconciliation cases. |
| Frontend | NOT IMPLEMENTED | Current investigation UI uses static demonstration data and has no backend case IDs. It was not connected to avoid displaying fabricated reports as real. |
| Actual PayPal Sandbox investigation | BLOCKED | No live database/provider verification was performed. The illustrative IDs from the request were not treated as evidence. |
| Production readiness | NOT COMPLETE | Requires authentication, a merchant-side order source, upstream case persistence, refund/accounting/fulfillment integrations, PostgreSQL migration execution, and real configured-provider verification. |

## Local test commands

From `backend/`:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q
python -m compileall -q app tests scripts alembic
alembic upgrade head
```

The pytest environment flag avoids an unrelated globally installed pytest
plugin that is incompatible with the local environment.
