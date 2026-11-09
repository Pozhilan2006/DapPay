# Event schema

The application is designed to normalize PayPal events and merchant-record updates into a common event model.

## Example fields

- `event_id`
- `source_system`
- `event_type`
- `status`
- `amount`
- `currency`
- `merchant_id`
- `created_at`
- `raw_payload`

## Use cases

- Duplicate-delivery detection
- Payment lineage tracing
- Reconciliation deltas
- AI investigation context
