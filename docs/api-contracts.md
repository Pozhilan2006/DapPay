# API contracts

This file tracks the contract surface of the FastAPI backend while the application is in foundation stage.

## Core routes

- `/api/health`
- `/api/payments`
- `/api/orders`
- `/api/webhooks`
- `/api/reconciliation`
- `/api/lineage`
- `/api/investigations`

## Contract approach

Use versioned schemas with clear pagination, filtering, and error envelopes as each domain is implemented.
