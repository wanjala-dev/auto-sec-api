import io
import os
from datetime import timedelta

import dj_database_url
import environ
import redis
from celery.schedules import crontab
from corsheaders.defaults import default_headers
from kombu import Exchange, Queue

from .base import *  # noqa: F403

# Dev MinIO is reachable from host at ``localhost:9100`` but from the
# Docker network at ``minio:9000``. Django/Celery use the internal
# hostname for uploads; the presigned URL the browser follows must use
# the host-reachable one so the signature + actual request URL match.
REPORT_PDF_S3_PUBLIC_ENDPOINT = os.environ.get("REPORT_PDF_S3_PUBLIC_ENDPOINT", "http://localhost:9100")


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ALLOWED_HOSTS = [
    ".localhost",
    "127.0.0.1:8010",
    "127.0.0.1",
    "api.local:8010",
    "100.126.180.103",
    "54.172.122.73",
    "d1ij8ii546ff6q.cloudfront.net",
]

# Application definition
SITE_ID = 2

env = environ.Env(DEBUG=(bool, False))
env_file = os.path.join(BASE_DIR, ".env")

if os.path.isfile(env_file):
    env.read_env(env_file)
elif os.getenv("TRAMPOLINE_CI", None):
    placeholder = f"SECRET_KEY=a\nDATABASE_URL=sqlite://{os.path.join(BASE_DIR, 'db.sqlite3')}"
    env.read_env(io.StringIO(placeholder))
elif os.environ.get("KUBERNETES_SERVICE_HOST", None):
    pass
else:
    raise Exception(
        "No local .env file or Kubernetes environment detected. "
        f"Create {env_file} (copy from .env.example) or unset DJANGO_SETTINGS_MODULE=api.settings.local."
    )


SECRET_KEY = env("SECRET_KEY")
SUPER_USER_PASSWORD = env("SUPER_USER_PASSWORD")

DEBUG = True

ALLOWED_HOSTS = [
    ".localhost",
    "api.local",
    ".api.local",
    "54.172.122.73",
    "d1ij8ii546ff6q.cloudfront.net",
    "*",
]

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfies")
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

DEFAULT_FILE_STORAGE = "infrastructure.storage.backends.LocalMediaStorage"
STATICFILES_STORAGE = "infrastructure.storage.backends.LocalStaticStorage"

LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "/"

EMAIL_USE_TLS = True
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_PORT = 587
# Per-attempt SMTP socket timeout (celery-tasks skill §3c) — keeps a hung
# email send from pinning a worker slot. Mirrors prod.py.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
# Console backend by default locally — emails (including invite magic-links)
# print to `make logs-web` so you can click them without SMTP. Override with
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend in .env to use
# Gmail/SES once credentials are valid.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Auto-Sec <info@octopusintl.org>")
DEFAULT_EMAIL_FROM = DEFAULT_FROM_EMAIL


# Stripe Configuration
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_BASIC_PRICE_ID = env("STRIPE_BASIC_PRICE_ID", default=None)
STRIPE_PRO_PRICE_ID = env("STRIPE_PRO_PRICE_ID", default=None)
STRIPE_SPONSOR_MONTHLY_PRICE_ID = env("STRIPE_SPONSOR_MONTHLY_PRICE_ID", default=None)
STRIPE_SPONSOR_YEARLY_PRICE_ID = env("STRIPE_SPONSOR_YEARLY_PRICE_ID", default=None)
STRIPE_DEFAULT_CURRENCY = env("STRIPE_DEFAULT_CURRENCY", default="usd")
STRIPE_WEBHOOK_KEY = env("STRIPE_WEBHOOK_KEY")
STRIPE_CONNECT_WEBHOOK_SECRET = env("STRIPE_CONNECT_WEBHOOK_SECRET", default="")
STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET = env(
    "STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET",
    default="",
)
STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET = env("STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET", default="")
SUBSCRIPTION_WEBHOOK_URL = env("SUBSCRIPTION_WEBHOOK_URL", default="")
WORKSPACE_BILLING_WEBHOOK_URL = env("WORKSPACE_BILLING_WEBHOOK_URL", default="")
# auto-sec frontend dev server runs on :3001 (:3000 is the original literacyseed).
# Email links (password reset, email verification) are built against this base.
LOCALHOST_FRONTEND_URL = env("LOCALHOST_FRONTEND_URL", default="http://localhost:3001")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3001")

LANGFUSE_SECRET_KEY = env("LANGFUSE_SECRET_KEY", default="")
LANGFUSE_PUBLIC_KEY = env("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_BASE_URL = env("LANGFUSE_BASE_URL", default="http://langfuse:3000")
LANGFUSE_HOST = env("LANGFUSE_HOST", default="http://langfuse:3000")


STRIPE_DEFAULT_PRICING_TIERS = [
    {
        "plan": "free",
        "price_id": None,
        "currency": STRIPE_DEFAULT_CURRENCY,
        "display_name": "Free",
        "monthly_amount": 0,
        "limits": {
            "max_projects": 300,
            "max_members": 100,
            "max_tasks": 100,
        },
    },
]

if STRIPE_BASIC_PRICE_ID:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "basic",
            "price_id": STRIPE_BASIC_PRICE_ID,
            "currency": STRIPE_DEFAULT_CURRENCY,
            "display_name": "Basic",
            "monthly_amount": 5,
            "limits": {
                "max_projects": 10,
                "max_members": 15,
                "max_tasks": 30,
            },
        }
    )

if STRIPE_PRO_PRICE_ID:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "pro",
            "price_id": STRIPE_PRO_PRICE_ID,
            "currency": STRIPE_DEFAULT_CURRENCY,
            "display_name": "Pro",
            "monthly_amount": 10,
            "limits": {
                "max_projects": 25,
                "max_members": 50,
                "max_tasks": 100,
            },
        }
    )

if STRIPE_SPONSOR_MONTHLY_PRICE_ID:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "Monthly sponsorship",
            "price_id": STRIPE_SPONSOR_MONTHLY_PRICE_ID,
            "currency": STRIPE_DEFAULT_CURRENCY,
        }
    )

if STRIPE_SPONSOR_YEARLY_PRICE_ID:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "Yearly sponsorship",
            "price_id": STRIPE_SPONSOR_YEARLY_PRICE_ID,
            "currency": STRIPE_DEFAULT_CURRENCY,
        }
    )

STRIPE_DEFAULT_WEBHOOKS = [
    {
        "name": "sponsorship",
        "signing_secret": STRIPE_WEBHOOK_KEY,
        "enabled": True,
        "url": "http://localhost:8010/sponsorship/sponsor/stripe/webhook?tenant=localhost",
    },
    {
        "name": "donations",
        "signing_secret": STRIPE_WEBHOOK_KEY,
        "enabled": True,
        "url": "http://api.local:8000/sponsorship/donations/campaign/stripe/webhook/?tenant=localhost",
    },
    {
        "name": "team",
        "signing_secret": STRIPE_WEBHOOK_KEY,
        "enabled": True,
        "url": "http://localhost:8010/team/stripe/webhook/",
    },
]

# Braintree fallback credentials (used when a workspace hasn't supplied its own).
# NOTE: Braintree is gated behind the `payments.braintree` FeatureFlag (see
# infrastructure/persistence/core/models.py FeatureFlag). When the flag is
# disabled (default for launch), the gateway is not registered and the public
# Braintree controllers return 503. Marketplace / sub-merchant onboarding is a
# separate post-launch project — flip the flag on once that ships.
BRAINTREE_MERCHANT_ID = env("BRAINTREE_MERCHANT_ID", default="")
BRAINTREE_PUBLIC_KEY = env("BRAINTREE_PUBLIC_KEY", default="")
BRAINTREE_PRIVATE_KEY = env("BRAINTREE_PRIVATE_KEY", default="")
BRAINTREE_ENVIRONMENT = env("BRAINTREE_ENVIRONMENT", default="sandbox")
BRAINTREE_MERCHANT_ACCOUNT_ID = env("BRAINTREE_MERCHANT_ACCOUNT_ID", default=None)
BRAINTREE_VENMO_MERCHANT_ACCOUNT_ID = env("BRAINTREE_VENMO_MERCHANT_ACCOUNT_ID", default=None)


ART_API_URL = env("ART_API_URL")
LTG_API_URL = env("LTG_API_URL")
WORKSPACE_API_URL = env("WORKSPACE_API_URL", default="http://localhost:8010/workspaces")


OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
HUGGINGING_FACE_ACCESS_TOKEN = env("HUGGINGING_FACE_ACCESS_TOKEN", default="")

# Elasticsearch was dropped in the auto-sec fork. Defaults keep settings
# import-safe when the ES service isn't running (search is not wired here).
ELASTICSEARCH_PASSWORD = env("ELASTICSEARCH_PASSWORD", default="")
ELASTICSEARCH_HOST = env("ELASTICSEARCH_HOST", default="http://localhost:9200")


EMAIL_CLICK_REDIRECT_LINK = env("EMAIL_CLICK_REDIRECT_LINK", default=None)
# Canonical confirm page (same as prod). The legacy /EmailConfirmed/ default
# used to drop the ?token= across the frontend's bare <Navigate> redirect,
# stranding fresh signups unverified — caught by the QA E2E lifecycle suite.
EMAIL_CONFIRMATION_REDIRECT_PATH = env("EMAIL_CONFIRMATION_REDIRECT_PATH", default="/identity/email-confirmed")


# LOCAL DEV throttle relief. The identity auth throttles (login / email-verify /
# password-reset) are keyed by IP; from a single dev machine, repeated manual
# testing and the QA E2E lifecycle suite (register → verify → login, many runs)
# trip the 15/hour email-verify cap and 10/min login cap, producing spurious
# 429s that look like flakes. Relax these on the LOCAL dev server only — prod
# and the test-gate settings inherit the real base rates untouched.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405 — from base import *
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}),  # noqa: F405
        "auth_login": "1000/min",
        "auth_email_verify": "1000/hour",
        "auth_password_reset_request": "1000/hour",
        "auth_password_reset_confirm": "1000/hour",
    },
}


# Single-DB in the auto-sec fork. The nonprofit multi-tenant DB routing
# (workspace/art/ltg aliases + TenantRouter) was dropped; everything lives on
# `default`. "workspace" is retained as the row-level tenant boundary only.
DATABASES = {
    "default": dj_database_url.config(default=env("DATABASE_URL")),
}

DB_POOL_ENABLED = env.bool("DB_POOL_ENABLED", default=False)
if DB_POOL_ENABLED:
    pool_max_size = env.int("DB_POOL_MAX_SIZE", default=0)
    if pool_max_size <= 0:
        pool_setting = True
    else:
        pool_setting = {
            "min_size": env.int("DB_POOL_MIN_SIZE", default=1),
            "max_size": pool_max_size,
            "timeout": env.float("DB_POOL_TIMEOUT", default=10.0),
            "max_idle": env.int("DB_POOL_MAX_IDLE", default=300),
            "max_lifetime": env.int("DB_POOL_MAX_LIFETIME", default=3600),
            "reconnect_timeout": env.float("DB_POOL_RECONNECT_TIMEOUT", default=5.0),
        }

    for db_config in DATABASES.values():
        if db_config.get("ENGINE") != "django.db.backends.postgresql":
            continue
        options = db_config.setdefault("OPTIONS", {})
        options["pool"] = pool_setting

# PgBouncer transaction-mode adjustments — see base.apply_pgbouncer_settings.
# Locally only the main DB (default/workspace) is routed through PgBouncer via
# DATABASE_URL; the rarely-used art/ltg tenant DBs stay direct. DISABLE_SERVER_
# SIDE_CURSORS on all aliases is harmless. DB_USE_DIRECT (migrations) repoints
# everything back to db:5432. No-op unless DB_PGBOUNCER / DB_USE_DIRECT are set.
apply_pgbouncer_settings(DATABASES)  # noqa: F405

OPEN_AI_SECRET_KEY = env("OPEN_AI_SECRET_KEY", default="")

CORS_ORIGIN_ALLOW_ALL = True

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:9000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "https://www.literacyseed.com",
    "https://api.wanjala.art",
    "https://www.api.wanjala.art",
    "https://d1ij8ii546ff6q.cloudfront.net",
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "cache-control",
    "pragma",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
]

CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",
    "http://127.0.0.1:8080",
    "https://www.literacyseed.com",
    "https://api.wanjala.art",
    "https://www.api.wanjала.art",
    "https://d1ij8ii546ff6q.cloudfront.net",
]

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"console_format": {"format": "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"}},
    "handlers": {"console": {"level": "DEBUG", "class": "logging.StreamHandler", "formatter": "console_format"}},
    "loggers": {
        "django": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "django.db.backends": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "apps": {
            "level": "DEBUG",
            "handlers": ["console"],
            "propagate": False,
        },
        "celery": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=20),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("SECRET_KEY"),
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "JWK_URL": None,
    "LEEWAY": 0,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(days=10),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=20),
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760


INTERNAL_IPS = ["127.0.0.1"]

DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
}


redis_host = env("REDIS_SERVICE_HOST")

REDIS = redis.Redis(
    host=redis_host,
    port=6379,
    db=3,
    charset="utf-8",
    decode_responses=True,
)


CELERY_QUEUE_DEFAULT = "default"
CELERY_QUEUE_OTHER = "other"
CELERY_QUEUE_AI_TEAMMATE = "ai_teammate"
CELERY_QUEUE_WORKSPACE_AGGREGATIONS = "workspace_aggregations"

CELERY_BROKER_URL = env("CELERY_BROKER", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_BACKEND", default="redis://127.0.0.1:6379/0")

CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Vancouver"

CELERY_DEFAULT_EXCHANGE_TYPE = "direct"

CELERY_BEAT_SCHEDULER = "celery.beat:PersistentScheduler"

CELERY_QUEUES = (
    Queue(CELERY_QUEUE_DEFAULT, Exchange(CELERY_QUEUE_DEFAULT), routing_key=CELERY_QUEUE_DEFAULT),
    Queue(
        CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
        Exchange(CELERY_QUEUE_WORKSPACE_AGGREGATIONS),
        routing_key=CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
    ),
    Queue(CELERY_QUEUE_AI_TEAMMATE, Exchange(CELERY_QUEUE_AI_TEAMMATE), routing_key=CELERY_QUEUE_AI_TEAMMATE),
)

CELERY_ROUTES = {
    "infrastructure.workspaces.aggregations.tasks.*": {
        "queue": CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
        "routing_key": CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
    },
    "ai.agents.tasks.run_ai_teammate_cycle": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    "ai.agents.tasks.schedule_ai_teammate_runs": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    "ai.agents.tasks.run_agent_execution": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
}

CELERY_DEFAULT_QUEUE = CELERY_QUEUE_DEFAULT

CELERY_TASK_TIME_LIMIT = int(env("CELERY_TASK_TIME_LIMIT", default=300))
CELERY_TASK_SOFT_TIME_LIMIT = int(env("CELERY_TASK_SOFT_TIME_LIMIT", default=270))
CELERY_TASK_DEFAULT_RETRY_DELAY = int(env("CELERY_TASK_DEFAULT_RETRY_DELAY", default=60))
CELERY_TASK_DEFAULT_MAX_RETRIES = int(env("CELERY_TASK_DEFAULT_MAX_RETRIES", default=3))
CELERY_TASK_ANNOTATIONS = {
    "*": {
        "max_retries": CELERY_TASK_DEFAULT_MAX_RETRIES,
        "default_retry_delay": CELERY_TASK_DEFAULT_RETRY_DELAY,
    }
}

CELERY_BROKER_CONNECTION_MAX_RETRIES = int(env("CELERY_BROKER_CONNECTION_MAX_RETRIES", default=5))
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": int(env("CELERY_VISIBILITY_TIMEOUT", default=3600)),
}

CELERY_BEAT_SCHEDULE = {
    # ── auto-sec kept schedules (nonprofit aggregation/search/payment
    # beats removed in the fork). Task names reference kept task modules; add
    # security-domain schedules (alert sweeps, agent runs) here as they ship.
    "identity_sweep_user_sessions": {
        "task": "identity.sweep_user_sessions",
        "schedule": crontab(minute="*/15"),
    },
    # Weekly push/delivery hygiene: delete PushSubscription rows dead
    # (expired/revoked) > PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS, expire active
    # subscriptions unseen > PUSH_SUBSCRIPTION_STALE_AFTER_DAYS, and prune
    # terminal NotificationDelivery ledger rows >
    # NOTIFICATION_DELIVERY_RETENTION_DAYS. Idempotent reconciliation.
    "notifications_prune_stale_push_subscriptions": {
        "task": "notifications.prune_stale_push_subscriptions",
        "schedule": crontab(hour=4, minute=40, day_of_week=0),
    },
    "workflow_run_due_schedules": {
        "task": "workflow.run_due_schedules",
        "schedule": crontab(minute="*"),
    },
    "sweep_stuck_document_imports": {
        "task": "sweep_stuck_document_imports",
        "schedule": crontab(minute="*/10"),
    },
    "signoff_materialize_pending_tasks": {
        "task": "sign_off.materialize_pending_signoff_tasks",
        "schedule": crontab(minute="*/5"),
    },
    # AI teammate cycle — fans out to run_ai_teammate_cycle for every
    # AI-enabled workspace, which runs the detector cycle (LogWatchErrorDetector
    # → evidence findings via the AIAction path, LogTriageRouterDetector →
    # triage agent). This is what makes the SOC log-watch → triage pipeline
    # run autonomously every 5 minutes.
    "schedule_ai_teammate_runs": {
        "task": "infrastructure.ai.agents.tasks.schedule_ai_teammate_runs",
        "schedule": crontab(minute="*/5"),
    },
    # Daily AI-action rollup — recomputes yesterday's AiActionDailyRollup
    # rows (runs, tool calls, tokens, spend). The posture dashboard's
    # governance charts read these rollup rows instead of live-aggregating
    # DeepRun/DeepRunLog on the request path.
    "rollup_ai_action_daily": {
        "task": "ai.rollup_ai_action_daily",
        "schedule": crontab(minute=20, hour=0),
    },
}

ELASTICSEARCH_DSL = {
    "default": {
        "hosts": ELASTICSEARCH_HOST,
        "http_auth": ("elastic", ELASTICSEARCH_PASSWORD),
        "verify_certs": False,
        "timeout": 60,
    }
}

# Local dev runs on pgvector + postgres search (CLAUDE.md "Dynamic
# Providers" rule). Keep django_elasticsearch_dsl installed so the test
# suite that DOES exercise ES can still import the documents, but
# silence its post_save signal handlers — without this, every model
# save tries to PUT to elasticsearch:9200, which isn't running locally,
# and the seed-on-startup commands crash the web container in a loop.
# Matches the test.py pattern (api/settings/test.py:112).
ELASTICSEARCH_DSL_AUTOSYNC = False
