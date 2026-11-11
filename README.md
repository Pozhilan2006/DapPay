# PayRecon AI

PayRecon AI is a production-oriented monorepo for financial intelligence and reconciliation workflows across PayPal activity and merchant records.

## Monorepo layout

- `backend/` — FastAPI-based service, SQLAlchemy models, reconciliation logic, AI investigation workflows.
- `frontend/` — Next.js dashboard for transaction monitoring, reconciliation, lineage visualization, and investigation views.
- `docs/` — Architecture, schema, integration, and team documentation.
- `scripts/` — Setup automation for local onboarding.
- `postman/` — API collection templates.

## Repository goals

- Clear ownership boundaries between backend domains.
- Scalable structure for three independent contributors.
- Production-ready local development and deployment workflow.
- Placeholder architecture for future business logic and integrations.

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

### Infrastructure

```bash
docker compose up --build
```

## Team ownership

- Member 1: PayPal integration, backend infrastructure, payments/webhooks, database and API contracts.
- Member 2: Reconciliation engine, lineage, anomaly detection, investigation workflows, and AI evidence retrieval.
- Member 3: Frontend experience, dashboards, investigations UI, system observability, and deployment configuration.

## Current status

PayPal order/capture persistence, webhook ingestion, database-backed
reconciliation, lineage, and an evidence-grounded backend investigation
workflow are present. Reconciliation persists only genuine deterministic
exception cases, keyed by stable case IDs. Completed matching payments can be
checked through the read-only transaction-review endpoint without being
misclassified as exceptions. Merchant-side, accounting, fulfillment,
refund-level integrations and application authentication remain incomplete.
The frontend investigation screen still uses demonstration data and is not
connected to the investigation API.

See [AI root-cause investigation](docs/ai-root-cause-investigation.md) for
workflow details, API routes, local setup, coverage, and limitations.
