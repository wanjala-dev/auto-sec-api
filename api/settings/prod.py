"""
Production settings for wanjala-api-v2.0
"""

import os
from datetime import timedelta

import environ
from celery.schedules import crontab
from corsheaders.defaults import default_headers
from kombu import Exchange, Queue

from .base import *  # noqa: F403

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Read environment variables ──────────────────────────────────────────────
env = environ.Env(DEBUG=(bool, False))
env_file = os.path.join(BASE_DIR, ".env")
if os.path.isfile(env_file):
    env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY")

# ── Email (AWS SES) ────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="email-smtp.us-east-1.amazonaws.com")
EMAIL_PORT = 587
EMAIL_USE_TLS = True
# celery-tasks skill §3c (backoff ≠ timeout): bound every SMTP/SES send with a
# per-attempt socket timeout. Without it a hung SES connection pins a Celery
# worker slot until the task's hard time-limit SIGKILLs it — and under
# worker_prefetch_multiplier=1 that's a whole worker doing nothing. Applies to
# every email task at once (contact form, donation/sponsorship notifications,
# newsletters, KYC staff notices).
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
EMAIL_HOST_USER = env("SES_SMTP_USER", default=env("EMAIL_HOST_USER", default=""))
EMAIL_HOST_PASSWORD = env("SES_SMTP_PASSWORD", default=env("EMAIL_HOST_PASSWORD", default=""))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Auto-Sec <info@octopusintl.org>")
SERVER_EMAIL = env("SERVER_EMAIL", default="Auto-Sec <info@octopusintl.org>")
# Newsletter dispatch knobs. ``EMAIL_FROM`` is the address-only form
# used by the per-recipient newsletter adapter when stitching together
# ``From: "{workspace_name}" <info@octopusintl.org>``. ``EMAIL_UNSUBSCRIBE_MAILTO``
# fills the second slot of the RFC 8058 ``List-Unsubscribe`` header so
# strict-CSP inbox clients can still unsubscribe via a mailto.
EMAIL_FROM = env("EMAIL_FROM", default="info@octopusintl.org")
EMAIL_UNSUBSCRIBE_MAILTO = env("EMAIL_UNSUBSCRIBE_MAILTO", default="unsubscribe@octopusintl.org")
# SES bounce + complaint SNS topic ARN — set to the topic that the SES
# configuration set forwards bounces + complaints to. When empty, the
# SNS handler rejects ALL inbound notifications as topic-mismatch (safe
# default: in a misconfigured environment, we'd rather reject than
# trust unverified events).
SES_SNS_TOPIC_ARN = env("SES_SNS_TOPIC_ARN", default="")

# ── Stripe ──────────────────────────────────────────────────────────────────
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_BASIC_PRICE_ID = env("STRIPE_BASIC_PRICE_ID", default=None)
STRIPE_PRO_PRICE_ID = env("STRIPE_PRO_PRICE_ID", default=None)
STRIPE_SPONSOR_MONTHLY_PRICE_ID = env("STRIPE_SPONSOR_MONTHLY_PRICE_ID", default=None)
STRIPE_SPONSOR_YEARLY_PRICE_ID = env("STRIPE_SPONSOR_YEARLY_PRICE_ID", default=None)
STRIPE_DEFAULT_CURRENCY = env("STRIPE_DEFAULT_CURRENCY", default="usd")
STRIPE_WEBHOOK_KEY = env("STRIPE_WEBHOOK_KEY", default="")
STRIPE_CONNECT_WEBHOOK_SECRET = env("STRIPE_CONNECT_WEBHOOK_SECRET", default="")
STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET = env("STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET", default="")
STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET = env("STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET", default="")
SUBSCRIPTION_WEBHOOK_URL = env("SUBSCRIPTION_WEBHOOK_URL", default="")
WORKSPACE_BILLING_WEBHOOK_URL = env("WORKSPACE_BILLING_WEBHOOK_URL", default="")
# FRONTEND_URL is the single source of truth — set it in .env on the server.
# LOCALHOST_FRONTEND_URL is the legacy name used by core_utils and email links.
FRONTEND_URL = env("FRONTEND_URL")
LOCALHOST_FRONTEND_URL = env("LOCALHOST_FRONTEND_URL", default=FRONTEND_URL)
EMAIL_CONFIRMATION_REDIRECT_PATH = env("EMAIL_CONFIRMATION_REDIRECT_PATH", default="/identity/email-confirmed")

# ── AI / LLM ───────────────────────────────────────────────────────────────
LANGFUSE_SECRET_KEY = env("LANGFUSE_SECRET_KEY", default="")
LANGFUSE_PUBLIC_KEY = env("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_BASE_URL = env("LANGFUSE_BASE_URL", default="")
OPEN_AI_SECRET_KEY = env("OPEN_AI_SECRET_KEY", default="")

# ── Tenant routing ──────────────────────────────────────────────────────────
ART_API_URL = env("ART_API_URL", default="api.wanjala.art")
LTG_API_URL = env("LTG_API_URL", default="api.wanjala.art")
WORKSPACE_API_URL = env("WORKSPACE_API_URL", default="api.wanjala.art")
EMAIL_CLICK_REDIRECT_LINK = env("EMAIL_CLICK_REDIRECT_LINK", default=FRONTEND_URL)

# ── Strip dev-only / heavy apps not needed in the lean EC2 stack ────────────
# Elasticsearch is replaced by pgvector + PostgreSQL full-text search.
# Haystack is unused (Solr backend, never deployed). django_seed is dev-only.
_EXCLUDED_APPS = {"django_elasticsearch_dsl", "haystack", "django_seed"}
INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in _EXCLUDED_APPS]

# Disable haystack since the app is removed
HAYSTACK_CONNECTIONS = {}

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
SITE_ID = 2

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

# ── CORS ────────────────────────────────────────────────────────────────────
CORS_ORIGIN_ALLOW_ALL = False
CORS_ALLOW_CREDENTIALS = True
# The landing site (octopusintl.org / www.octopusintl.org) calls the contact
# endpoint cross-origin; http://localhost:5173 is its local Vite preview, which
# hits this API directly (there is no local landing backend). Kept in the code
# default — an env override replaces the WHOLE list, so env-only additions
# silently mask future default changes.
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in env(
        "CORS_ALLOWED_ORIGINS",
        default="https://app.octopusintl.org,https://www.octopusintl.org,https://octopusintl.org,https://www.literacyseed.com,https://api.wanjala.art,https://d2wnv83yfoz6nw.cloudfront.net,https://demo.octopusintl.org,http://localhost:5173",
    ).split(",")
    if o.strip()
]
CORS_ALLOW_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]
CORS_ALLOW_HEADERS = list(default_headers) + [
    "cache-control",
    "pragma",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
]

# ── JWT ─────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760

# ── Redis ───────────────────────────────────────────────────────────────────
import redis  # noqa: E402

redis_host = env("REDIS_SERVICE_HOST", default="redis")
REDIS = redis.Redis(host=redis_host, port=6379, db=3, charset="utf-8", decode_responses=True)

# ── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console_format": {"format": "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"},
    },
    "handlers": {
        "console": {"level": "INFO", "class": "logging.StreamHandler", "formatter": "console_format"},
    },
    "loggers": {
        "django": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "celery": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}


def _parse_env_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_postgres_pool_options(prefix: str = "DB_POOL_") -> dict:
    """Build psycopg3 pool options for Django's PostgreSQL backend.

    Django's native pooling requires psycopg3 (`psycopg`) with the pool extra
    installed. When psycopg2 is used, Django ignores `OPTIONS["pool"]`.
    """
    enabled = _parse_env_bool(os.environ.get(f"{prefix}ENABLED"))
    if not enabled:
        return {}

    max_size = os.environ.get(f"{prefix}MAX_SIZE")
    if not max_size:
        return {"pool": True}

    def _int(name: str, default: int | None = None) -> int | None:
        raw = os.environ.get(f"{prefix}{name}")
        if raw is None:
            return default
        raw = raw.strip()
        if not raw:
            return default
        return int(raw)

    def _float(name: str, default: float | None = None) -> float | None:
        raw = os.environ.get(f"{prefix}{name}")
        if raw is None:
            return default
        raw = raw.strip()
        if not raw:
            return default
        return float(raw)

    pool = {
        "min_size": _int("MIN_SIZE", 1),
        "max_size": int(max_size),
        "timeout": _float("TIMEOUT"),
        "max_idle": _int("MAX_IDLE"),
        "max_lifetime": _int("MAX_LIFETIME"),
        "reconnect_timeout": _float("RECONNECT_TIMEOUT"),
    }
    pool = {k: v for k, v in pool.items() if v is not None}
    return {"pool": pool}


# Database — single PG instance, all aliases point to the same DB.
# The tenant router expects workspace/art/linkthegap aliases to exist.
_DEFAULT_DB = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("DB_NAME", os.environ.get("POSTGRES_DB", "wanjala-api-database")),
    "USER": os.environ.get("DB_USER", os.environ.get("POSTGRES_USER", "wanjala-art-sql-user")),
    "PASSWORD": os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "")),
    "HOST": os.environ.get("DB_HOST", "db"),
    "PORT": os.environ.get("DB_PORT", "5432"),
    "OPTIONS": _build_postgres_pool_options(),
}
DATABASES = {
    "default": _DEFAULT_DB,
    "workspace": {**_DEFAULT_DB},
    "art": {**_DEFAULT_DB},
    "linkthegap": {**_DEFAULT_DB},
}

# Apply PgBouncer transaction-mode adjustments (DISABLE_SERVER_SIDE_CURSORS when
# DB_PGBOUNCER=true; bypass the pooler at db:5432 when DB_USE_DIRECT=true, e.g.
# migrations). No-op unless those env vars are set — a direct-to-Postgres deploy
# is unchanged.
apply_pgbouncer_settings(DATABASES)  # noqa: F405

# Static files stay on local disk -- collectstatic regenerates them
# on every deploy and there's nothing to back up.
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"

# MEDIA_ROOT is kept defined (pointing at the legacy on-disk location)
# even though writes go straight to S3 via S3MediaStorage. Two reasons:
# (a) Any code path that still constructs paths from settings.MEDIA_ROOT
#     gets something sane instead of falling back to Django's default
#     of "" which resolves to the container cwd (/app).
# (b) The `migrate_media_to_s3` management command walks this directory
#     to lift pre-existing files into S3 -- without MEDIA_ROOT set, it
#     would walk the entire repo. After the lift completes and we've
#     verified nothing left on disk, this line can be deleted.
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Media files live in S3 in prod -- the EC2 disk has no role in
# serving user uploads after this PR, so the instance becomes
# effectively stateless from a media standpoint. AWS_LOCATION =
# "media" routes uploads into the `media/` prefix of the shared
# data bucket, alongside backup/ but isolated at the IAM-statement
# level on the EC2 instance role.
#
# Auth: NO explicit AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in
# this stack. boto3's default credential chain reaches the EC2
# instance metadata service (IMDSv2 at 169.254.169.254 from inside
# the container) and picks up `wanjala-demo-sandbox-host` role
# credentials transparently. Zero long-lived AWS keys on the host
# means no rotation problem and a leaked .env doesn't leak S3 access.
AWS_STORAGE_BUCKET_NAME = os.environ.get("MEDIA_S3_BUCKET", "wanjala-demo-sandbox-data")
AWS_S3_REGION_NAME = os.environ.get("MEDIA_S3_REGION", "us-east-1")
AWS_LOCATION = "media"
AWS_S3_ADDRESSING_STYLE = "virtual"
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
# 15 minutes is long enough for a single page-load to fetch every
# image without expiring mid-render; short enough that a leaked URL
# stops being useful before the day is out.
AWS_QUERYSTRING_EXPIRE = 60 * 15

# MEDIA_URL is informational once S3 takes over -- S3MediaStorage
# generates signed URLs directly via storage.url(). Kept set so any
# code path that still constructs URLs from MEDIA_URL gets a sane
# https origin instead of a broken /media/ path.
MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{AWS_LOCATION}/"

STORAGES = {
    "default": {
        "BACKEND": "infrastructure.storage.backends.S3MediaStorage",
    },
    "staticfiles": {
        "BACKEND": "infrastructure.storage.backends.LocalStaticStorage",
    },
}

CELERY_BEAT_SCHEDULE = {
    # auto-sec fork: nonprofit aggregation/search/payment/budget beats
    # removed. Only kept-context schedules remain.
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
}

CELERY_QUEUE_DEFAULT = os.environ.get("CELERY_QUEUE_DEFAULT", "default")
CELERY_QUEUE_AI_TEAMMATE = os.environ.get("CELERY_QUEUE_AI_TEAMMATE", "ai_teammate")
CELERY_QUEUE_WORKSPACE_AGGREGATIONS = os.environ.get("CELERY_QUEUE_WORKSPACE_AGGREGATIONS", "workspace_aggregations")
# Dedicated queue for latency-sensitive payment webhook / donation tasks so
# slow aggregations or AI work on `default` can't starve Stripe event processing.
CELERY_QUEUE_PAYMENTS = os.environ.get("CELERY_QUEUE_PAYMENTS", "payments")

CELERY_TASK_DEFAULT_QUEUE = CELERY_QUEUE_DEFAULT
CELERY_QUEUES = (
    Queue(CELERY_QUEUE_DEFAULT, Exchange(CELERY_QUEUE_DEFAULT), routing_key=CELERY_QUEUE_DEFAULT),
    Queue(CELERY_QUEUE_AI_TEAMMATE, Exchange(CELERY_QUEUE_AI_TEAMMATE), routing_key=CELERY_QUEUE_AI_TEAMMATE),
    Queue(
        CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
        Exchange(CELERY_QUEUE_WORKSPACE_AGGREGATIONS),
        routing_key=CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
    ),
    Queue(CELERY_QUEUE_PAYMENTS, Exchange(CELERY_QUEUE_PAYMENTS), routing_key=CELERY_QUEUE_PAYMENTS),
)

CELERY_ROUTES = {
    # Payments — latency-sensitive Stripe webhook + donation delivery.
    "process_payment_event": {
        "queue": CELERY_QUEUE_PAYMENTS,
        "routing_key": CELERY_QUEUE_PAYMENTS,
    },
    "send_donation_notification": {
        "queue": CELERY_QUEUE_PAYMENTS,
        "routing_key": CELERY_QUEUE_PAYMENTS,
    },
    "infrastructure.workspaces.aggregations.tasks.*": {
        "queue": CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
        "routing_key": CELERY_QUEUE_WORKSPACE_AGGREGATIONS,
    },
    "infrastructure.ai.agents.tasks.schedule_ai_teammate_runs": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    "infrastructure.ai.agents.tasks.run_ai_teammate_cycle": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    "infrastructure.ai.agents.tasks.run_agent_execution": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    # Embedding tasks should run on the ai_teammate queue too
    "infrastructure.ai.embeddings.tasks.create_embeddings_for_workspace": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    "infrastructure.ai.embeddings.tasks.create_embeddings_for_workspace_content": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
    "infrastructure.ai.embeddings.tasks.create_embeddings_for_conversations": {
        "queue": CELERY_QUEUE_AI_TEAMMATE,
        "routing_key": CELERY_QUEUE_AI_TEAMMATE,
    },
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", os.environ.get("CELERY_BROKER", "redis://redis:6379/0"))
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", os.environ.get("CELERY_BACKEND", CELERY_BROKER_URL))
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = os.environ.get("CELERY_TIMEZONE", "UTC")

CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", 300))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", 270))
CELERY_TASK_DEFAULT_RETRY_DELAY = int(os.environ.get("CELERY_TASK_DEFAULT_RETRY_DELAY", 60))
CELERY_TASK_DEFAULT_MAX_RETRIES = int(os.environ.get("CELERY_TASK_DEFAULT_MAX_RETRIES", 3))
CELERY_TASK_ANNOTATIONS = {
    "*": {
        "max_retries": CELERY_TASK_DEFAULT_MAX_RETRIES,
        "default_retry_delay": CELERY_TASK_DEFAULT_RETRY_DELAY,
    }
}

CELERY_BROKER_CONNECTION_MAX_RETRIES = int(os.environ.get("CELERY_BROKER_CONNECTION_MAX_RETRIES", 5))
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": int(os.environ.get("CELERY_VISIBILITY_TIMEOUT", 3600)),
}

# Lossless-deploy reliability — see celery-tasks skill rule 5.
# Without ACKS_LATE, an in-flight task is acknowledged the moment a worker
# picks it up, so a SIGKILL/SIGTERM during a deploy silently drops the work.
# The trade-off is duplicate execution on the (rare) crash-after-completion
# path, which is why every task MUST be idempotent (rule 2).
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.environ.get("CELERY_WORKER_PREFETCH_MULTIPLIER", 1))
CELERY_WORKER_MAX_TASKS_PER_CHILD = int(os.environ.get("CELERY_WORKER_MAX_TASKS_PER_CHILD", 50))
CELERY_RESULT_EXPIRES = int(os.environ.get("CELERY_RESULT_EXPIRES", 3600))
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# Security settings for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Env-driven like CORS_ALLOWED_ORIGINS. app.octopusintl.org is the canonical
# frontend domain; the raw CloudFront URL stays as a legacy alias.
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in env(
        "CSRF_TRUSTED_ORIGINS",
        default="https://api.wanjala.art,https://app.octopusintl.org,https://www.octopusintl.org,https://octopusintl.org,https://d2wnv83yfoz6nw.cloudfront.net,https://demo.octopusintl.org",
    ).split(",")
    if o.strip()
]
