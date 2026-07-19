# Seed Payments API

Short guide for the frontend to manage per-seed payment methods.

## Resources
- `GET /workspaces/payments/providers/` – catalog of providers and their capability metadata.
- `GET/POST /workspaces/payments/workspaces/<seed_id>/methods/` – list or create methods.
- `GET/PATCH /workspaces/payments/workspaces/<seed_id>/methods/<id>/` – manage a method.
- `POST /workspaces/payments/workspaces/<seed_id>/methods/<id>/set-primary/` – mark a method primary (per provider/seed).
- `POST /workspaces/payments/workspaces/<seed_id>/methods/<id>/webhooks/` – create/rotate a webhook endpoint + secret for the method.
- `POST /workspaces/payments/workspaces/<seed_id>/methods/<id>/plans/` – create/list plans.
- `PATCH/DELETE /workspaces/payments/workspaces/<seed_id>/methods/<id>/plans/<plan_id>/` – update or remove a plan.
- Public catalog for donors: `GET /workspaces/payments/public/workspaces/<seed_id>/?context=<context>&child_id=<uuid>` returns publishable methods + plans only.

## Required fields
- `display_name`: Shown to admins/donors.
- `provider`: Provider slug (e.g., `stripe`, `bitpay`).
- `enabled_contexts`: Array of contexts this method can serve.
- `primary_contexts`: Optional contexts where this method should be preferred over the global primary.
- `credentials` (write-only, API providers):
  - Stripe: `{ "secret_key": "<sk_live_...>" }` (optional if `STRIPE_SECRET_KEY` is configured; add `publishable_key` if needed).
  - BitPay: `{ "token": "<merchant_token>" }`
  - Braintree: `{ "merchant_id": "...", "public_key": "...", "private_key": "..." }`
- `provider_account_id`: Optional provider account identifier (e.g., Stripe Connect account id; usually populated after onboarding).
- `allow_public_listing` (manual/offline): set true to include manual rails in the public catalog.

## Status lifecycle
- `draft` → `pending` → `active`/`requires_action` → `disabled`.
- `pending/active/requires_action` require valid credentials (either supplied now or already stored).
- One primary method per `(seed, provider)`; the `set-primary` action enforces this.

## Responses
- Credentials are never returned. Timestamps expose when secrets were last updated/tested:
  - `credentials_updated_at`: When secrets were last written.
  - `last_tested_at`: Optional timestamp for your “test connection” flow.
  - `last_error`/`last_error_at`: Latest provider error surfaced to admins.

## Client flow
1) Fetch providers, render config form based on `config_template`.
2) Create method with `display_name`, `provider`, `enabled_contexts`, and `credentials` (Stripe can omit credentials when the platform key is configured).
3) Optionally set primary via `set-primary`.
4) Create plans under the method; plans validate `interval`, `amount`, and `context`.
5) If provider needs OAuth (e.g., Stripe Connect), hit the `authorize` endpoint to get redirect URLs and store returned account id in `provider_account_id`.
6) Handle errors by reading `last_error` and retrying with updated credentials; surface validation errors from the API directly to the admin UI.

## Testing
- Unit tests live in `seed/payments/tests/`; run `pytest api-v2.0/seed/payments/tests` to validate serializers and helpers.
