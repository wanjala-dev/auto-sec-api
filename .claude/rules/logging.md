---
description: Structured logging, error reporting, and PII filtering standards
globs: "**/*.py"
alwaysApply: false
---

# Logging Standards

Rules for what to log, how to log it, and what NEVER to log. Loosely modeled on Themis's `logging.md` (filter-parameter approach to PII), adapted for Python + Django + DRF + Celery.

**Mental model:** logs are code. They end up in Kibana / Cloudwatch / grep-able files; they are searched weeks later by someone debugging an incident. A log line that doesn't name the entity (workspace_id, task name, user_id) is useless noise. A log line that includes a password or Stripe secret is a breach.

The full deep playbook — worked examples per anti-pattern, structured `extra={}` recipes, OpenTelemetry trace-correlation wiring, logger placement in the hexagonal layers, the ELK-alternatives backend comparison, the `caplog` test pattern, and the pre-merge checklist — lives in the **`logging` skill** (`.claude/skills/logging/SKILL.md`) and the **logging roadmap** (`docs/plans/LOGGING_ROADMAP.md`). Invoke the skill when actively writing or reviewing logging code.

## 1. Module-level logger, never `print()`

Every Python module that logs MUST declare a module-level logger and use it. Never `print()` in production code — it bypasses the handler pipeline and goes to stdout without level, context, or filtering.

```python
# CORRECT
import logging
logger = logging.getLogger(__name__)
logger.info("workspace_created workspace_id=%s user_id=%s", workspace.id, user.id)

# WRONG
print(f"Created workspace {workspace.id} for user {user.id}")
```

`__name__` gives hierarchical logger names (`components.sponsorship.application.service`) so global log config can tune noise per context.

## 2. Use `logger.exception()` for exceptions, never `logger.error(str(e))`

`logger.exception()` captures the traceback automatically. `logger.error(str(e))` or `logger.error("failed: %s", e)` loses it — you get "KeyError" with no stack trace, then spend 30 minutes re-deriving which line threw.

```python
# CORRECT — captures traceback
try:
    result = stripe.PaymentIntent.retrieve(pi_id)
except stripe.error.StripeError:
    logger.exception("stripe payment_intent retrieve failed pi=%s", pi_id)
    raise

# WRONG — traceback lost
try:
    result = stripe.PaymentIntent.retrieve(pi_id)
except stripe.error.StripeError as e:
    logger.error("stripe failed: %s", str(e))
    raise
```

`logger.exception()` is `logger.error()` + auto-traceback. Use it inside `except` blocks.

## 3. Structured context every log line

Every log line MUST name the entity it's about. A line saying "processing failed" with no identifiers is noise. Use `%s`-style placeholders (lazy formatting) with `key=value` pairs for greppability.

```python
# CORRECT — grep-able, identifies what failed
logger.info(
    "donation_webhook_processed donation_id=%s event_type=%s account_id=%s",
    donation.id, event.type, account_id,
)

# WRONG — can't grep, no ID
logger.info(f"Processing donation {donation}")
logger.info("processed webhook")
```

Standard keys by context:
- Requests: `user_id`, `workspace_id`, `request_id` (when available)
- Celery tasks: task name first (via formatter) + `task_id`, `workspace_id`
- Payment flows: `donation_id` / `payment_intent_id` / `charge_id`, `account_id` (Stripe connected account)
- AI flows: `agent_id`, `run_id`, `workspace_id`

## 4. Never log PII or secrets

The following MUST NEVER appear in log messages:

| Category | Examples |
|---|---|
| Auth | Passwords, password-reset codes, OTP secrets, session keys, JWT access/refresh tokens |
| Payment | Full card numbers, CVV, Stripe secret keys, Plaid access tokens, bank account/routing numbers |
| Webhooks | Raw Stripe webhook payloads (they contain PII + signatures), webhook signing secrets |
| Identity | Full user emails in bulk, phone numbers, government IDs, addresses |
| API keys | Any third-party API key or OAuth bearer |

**Email address is a gray area.** Logging a single email in context of a user-facing action (e.g. "verification email sent email_hash=..." where hash is a short non-reversible hash) is OK. Logging full inboxes in bulk (e.g. dumping a recipient list) is not. When in doubt, log the user ID — it's equally grep-able and isn't PII.

```python
# CORRECT
logger.info("password_reset_requested user_id=%s", user.id)
logger.info("stripe_webhook_received event_id=%s type=%s", event.id, event.type)

# WRONG — leaks raw webhook body
logger.info("stripe webhook: %s", request.body)
# WRONG — leaks email in logs
logger.info("login failed email=%s password=%s", email, password)
```

## 5. Apply Django's sensitive-params decorators to auth + webhook views

Django's default exception reporter (`DEFAULT_EXCEPTION_REPORTER_FILTER`) scrubs `password`, `secret`, `token`, `api_key` from error pages by default. But if your view handler takes `password`, `otp`, `token`, or webhook body as a POST parameter, you must explicitly mark them:

```python
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

@method_decorator(sensitive_post_parameters("password", "password_confirmation"), name="post")
class LoginController(APIView):
    def post(self, request):
        ...

@sensitive_variables("password", "raw_body", "signature")
def verify_password(password: str, ...):
    ...
```

This keeps the values out of Django's error pages AND out of error tracking (Sentry, Bugsnag) when an exception fires during the request. Apply to: login, register, change-password, reset-password, OTP verify, Stripe webhook handlers (body + signature), OAuth token exchange.

## 6. Log levels

| Level | When to use | Example |
|---|---|---|
| `DEBUG` | Dev-only diagnostics; disabled in prod | "cache miss flag=%s" |
| `INFO` | Significant business events | "donation_created donation_id=%s amount=%s" |
| `WARNING` | Degraded operation but not broken | "feature flag missing key=%s; defaulting to False" |
| `ERROR` | Broken but recoverable | "email send failed user_id=%s; retrying" |
| `EXCEPTION` | Same as ERROR but inside `except:` | Use `logger.exception(...)` |
| `CRITICAL` | Service is down / corrupted state | Almost never; prefer to raise |

Prod log level is typically `INFO`. `DEBUG` logs should never appear in prod — use them for dev-time diagnostics and assume they'll be filtered.

## 7. Never catch `Exception` just to log and swallow

A `try / except Exception: logger.exception(...); return None` that silently eats failures is worse than no handler — it hides bugs and makes incident analysis harder. Let exceptions propagate unless you have a specific, documented reason to catch.

```python
# CORRECT — only swallow what you understand
try:
    result = stripe.PaymentIntent.retrieve(pi_id)
except stripe.error.InvalidRequestError:
    logger.warning("stripe payment_intent not found pi=%s", pi_id)
    return None
except stripe.error.StripeError:
    logger.exception("stripe transient error pi=%s", pi_id)
    raise  # let Celery retry

# WRONG — swallows TypeError, AttributeError, KeyError, everything
try:
    result = stripe.PaymentIntent.retrieve(pi_id)
except Exception:
    logger.exception("something failed")
    return None
```

The one legitimate use for `except Exception` is in bulk per-item loops where you want to log-and-continue — see `components/sponsorship/infrastructure/tasks/ledger_tasks.py` for the pattern (per-item savepoint + `logger.exception` + continue).

## 8. Celery task logging

Task entry and completion MUST be logged at INFO so operators can grep a single task's lifecycle:

```python
@shared_task(name="process_payment_event", bind=True, ...)
def process_payment_event(self, payment_event_id: str, ...):
    logger.info(
        "process_payment_event started event_id=%s task_id=%s",
        payment_event_id, self.request.id,
    )
    result = _do_work(payment_event_id)
    logger.info(
        "process_payment_event completed event_id=%s task_id=%s",
        payment_event_id, self.request.id,
    )
    return result
```

Celery's own INFO-level logs show the dispatch + return — your task's INFO log shows the business outcome.

## 9. What NOT to log (summary)

- `print()` calls
- Full request bodies / JSON payloads
- Raw webhook payloads (they contain signatures + PII)
- Traceback-less `logger.error(str(e))` in `except` blocks
- Generic messages without an entity ID ("processing failed", "cache updated")
- Secrets, tokens, passwords, OTP codes — ever
- Loops that log per-row at INFO (use DEBUG or aggregate counts)

## 10. Testing logs

For tests that assert on log output, use pytest's built-in `caplog` fixture — never stub the logger module.

```python
def test_failed_donation_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="components.sponsorship"):
        process_failed_donation(donation_id)
    assert any(
        "donation_failed donation_id" in r.message for r in caplog.records
    )
```

See also:
- `.claude/rules/performance.md` — don't log per-row inside hot loops; use DEBUG or aggregate counts
- `celery-tasks` skill §10 — per-task logging conventions
- `CLAUDE.md` "Debugging & Error Handling Philosophy" — never silence errors with bandaid try/except
