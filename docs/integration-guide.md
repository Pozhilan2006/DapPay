# Integration guide

## PayPal integration scope

- Sandbox credential configuration
- Order and payment capture retrieval
- Webhook verification
- Event normalization and persistence

## Operational notes

The application is intentionally structured to isolate vendor-specific behaviors behind integration modules before they are consumed by domain services.
