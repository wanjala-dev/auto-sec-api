import os
from datetime import timedelta

from celery.schedules import crontab

from .base import *

# Path helper
location = lambda x: os.path.join(os.path.dirname(os.path.realpath(__file__)), x)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS",
    ".localhost,127.0.0.1,api.local,35.202.125.199,workspace.wanjala.art,api.charityseed.ca,ltg.wanjala.art,54.172.122.73,d1ij8ii546ff6q.cloudfront.net",
).split(",")


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ["SECRET_KEY"]

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "false").lower() in {"1", "true", "yes"}

if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")


EMAIL_USE_TLS = True
EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
EMAIL_PORT = 587
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
DEFAULT_EMAIL_FROM = "c0d3henry@gmail.com"


STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_BASIC_PRICE_ID = os.environ.get("STRIPE_BASIC_PRICE_ID")
STRIPE_PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID")
STRIPE_SPONSOR_MONTHLY_PRICE_ID = os.environ.get("STRIPE_SPONSOR_MONTHLY_PRICE_ID")
STRIPE_SPONSOR_YEARLY_PRICE_ID = os.environ.get("STRIPE_SPONSOR_YEARLY_PRICE_ID")
STRIPE_DEFAULT_CURRENCY = os.environ.get("STRIPE_DEFAULT_CURRENCY", "usd")
STRIPE_WEBHOOK_KEY = os.environ.get("STRIPE_WEBHOOK_KEY")
STRIPE_CONNECT_WEBHOOK_SECRET = os.environ.get("STRIPE_CONNECT_WEBHOOK_SECRET", "")
STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET = os.environ.get(
    "STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET",
    "",
)
STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET = os.environ.get("STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET")
SUBSCRIPTION_WEBHOOK_URL = os.environ.get("SUBSCRIPTION_WEBHOOK_URL", "")
WORKSPACE_BILLING_WEBHOOK_URL = os.environ.get("WORKSPACE_BILLING_WEBHOOK_URL", "")
LOCALHOST_FRONTEND_URL = os.environ.get("LOCALHOST_FRONTEND_URL", "http://localhost:3000")

STRIPE_DEFAULT_PRICING_TIERS = []

if os.environ.get("STRIPE_INCLUDE_FREE_TIER", "true").lower() in {"1", "true", "yes"}:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "free",
            "price_id": None,
            "currency": STRIPE_DEFAULT_CURRENCY,
        }
    )

if STRIPE_BASIC_PRICE_ID:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "basic",
            "price_id": STRIPE_BASIC_PRICE_ID,
            "currency": STRIPE_DEFAULT_CURRENCY,
        }
    )

if STRIPE_PRO_PRICE_ID:
    STRIPE_DEFAULT_PRICING_TIERS.append(
        {
            "plan": "pro",
            "price_id": STRIPE_PRO_PRICE_ID,
            "currency": STRIPE_DEFAULT_CURRENCY,
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

ART_API_URL = os.environ.get("ART_API_URL")
LTG_API_URL = os.environ.get("LTG_API_URL")
WORKSPACE_API_URL = os.environ.get("WORKSPACE_API_URL")

ACCEPTATION_URL = "https://wanjala.art"

DJANGO_ALLOWED_HOST_1 = "wanjala.art"

from corsheaders.defaults import default_headers

CORS_ALLOW_HEADERS = default_headers + ("Access-Control-Allow-Origin",)

CORS_ORIGIN_ALLOW_ALL = True


SITE_ID = 2

# allow upload big file
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024 * 15  # 15M
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE


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


_POSTGRES_POOL_OPTIONS = _build_postgres_pool_options()

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DEFAULT_DB"),
        "USER": os.environ.get("DEFAULT_USER"),
        "PASSWORD": os.environ.get("DEFAULT_PASSWORD"),
        "HOST": os.environ.get("DEFAULT_HOST"),
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 3,
            **_POSTGRES_POOL_OPTIONS,
        },
    },
    "workspace": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("WORKSPACE_DB"),
        "USER": os.environ.get("WORKSPACE_USER"),
        "PASSWORD": os.environ.get("WORKSPACE_PASSWORD"),
        "HOST": os.environ.get("WORKSPACE_HOST"),
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 3,
            **_POSTGRES_POOL_OPTIONS,
        },
    },
    "art": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("ART_DB"),
        "USER": os.environ.get("ART_USER"),
        "PASSWORD": os.environ.get("ART_PASSWORD"),
        "HOST": os.environ.get("ART_HOST"),
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 3,
            **_POSTGRES_POOL_OPTIONS,
        },
    },
    "linkthegap": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("LTG_DB"),
        "USER": os.environ.get("LTG_USER"),
        "PASSWORD": os.environ.get("LTG_PASSWORD"),
        "HOST": os.environ.get("LTG_HOST"),
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 3,
            **_POSTGRES_POOL_OPTIONS,
        },
    },
}

OPEN_AI_SECRET_KEY = os.environ.get("OPEN_AI_SECRET_KEY")

CORS_ORIGIN_ALLOW_ALL = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:9000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "https://www.literacyseed.com",
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

# CORS WHITELIST
CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",
    "http://127.0.0.1:8080",
    "https://www.literacyseed.com",
]

LOGGING = {
    "version": 1,
    "filters": {
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        }
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "filters": ["require_debug_true"],
            "class": "logging.StreamHandler",
        }
    },
    "loggers": {
        "django.db.backends": {
            "level": "DEBUG",
            "handlers": ["console"],
        }
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=20),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": os.environ.get("SECRET_KEY"),
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

UPLOAD_ROOT = "media/uploads/"


STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

# Storage backends - using local storage for development
STORAGES = {
    "default": {
        "BACKEND": "infrastructure.storage.backends.LocalMediaStorage",
    },
    "staticfiles": {
        "BACKEND": "infrastructure.storage.backends.LocalStaticStorage",
    },
}


# CELERY
CELERY_BROKER_URL = "redis://redis:6379/0"
CELERY_RESULT_BACKEND = "redis://redis:6379/0"
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

CELERY_BEAT_SCHEDULE = {
    # Daily login-session janitor: mark expired-but-unrevoked sessions as
    # revoked ("expired_sweep"), prune sessions dead > SESSION_RETENTION_DAYS,
    # prune AuthAuditEvent rows > AUTH_AUDIT_RETENTION_DAYS. Idempotent
    # reconciliation — 04:20 UTC keeps it clear of the 03:00-04:00 embedding
    # and demo-cleanup window.
    "identity_sweep_user_sessions": {
        "task": "identity.sweep_user_sessions",
        "schedule": crontab(hour=4, minute=20),
    },
    # Fire due recurring workflow schedules (user-defined daily/weekly/monthly
    # automations). Every minute so a scheduled time is honoured within ~60s;
    # the task is idempotent (advances next_run_at + per-fire idempotency key).
    "workflow_run_due_schedules": {
        "task": "workflow.run_due_schedules",
        "schedule": crontab(minute="*"),
    },
    "ai_teammate_schedule": {
        "task": "infrastructure.ai.agents.tasks.schedule_ai_teammate_runs",
        "schedule": timedelta(hours=1),
    },
    # Project pending sign-off items onto each workspace's AI Findings
    # Kanban board (assigned to the owner) + reconcile resolved cards.
    # Idempotent — safe to re-run every 15 min.
    "signoff_materialize_pending_tasks": {
        "task": "sign_off.materialize_pending_signoff_tasks",
        "schedule": crontab(minute="*/15"),
    },
    # Daily AI-action rollup — recomputes yesterday's AiActionDailyRollup
    # rows (runs, tool calls, tokens, spend). The posture dashboard's
    # governance charts read these rollup rows instead of live-aggregating
    # DeepRun/DeepRunLog on the request path.
    "rollup_ai_action_daily": {
        "task": "ai.rollup_ai_action_daily",
        "schedule": crontab(minute=20, hour=0),
    },
    "workspace_embeddings_hourly": {
        # Refresh embeddings for AI-enabled workspaces every hour in dev.
        # Only workspaces with ai_teammate_enabled=True are processed.
        "task": "infrastructure.ai.embeddings.tasks.create_embeddings_for_workspace_content",
        "schedule": timedelta(hours=1),
    },
    "workspace_setup_banner_sync": {
        "task": "infrastructure.workspaces.tasks.sync_workspace_setup_banners",
        "schedule": timedelta(minutes=30),
    },
    "workspace_temp_workspace_cleanup": {
        "task": "infrastructure.workspaces.tasks.prune_temporary_workspaces",
        "schedule": timedelta(hours=1),
    },
    "workspace_index_nightly_refresh": {
        # Re-embed every active workspace into the pgvector store so drift
        # (missed signals, partial saves) gets healed.  Hash-skip inside
        # the adapter means unchanged workspaces cost nothing.
        "task": "components.knowledge.workspace_index.reindex_all_workspaces",
        "schedule": crontab(hour=3, minute=45),
    },
    "index_freshness_slo_audit": {
        # Tier 3 #14 — see prod.py for the full description.
        "task": "components.knowledge.index_freshness.audit_index_freshness",
        "schedule": crontab(minute="*/10"),
    },
    "index_freshness_sample_prune": {
        # Tier 3 #14 — see prod.py for the full description.
        "task": "components.knowledge.index_freshness.prune_index_freshness_samples",
        "schedule": crontab(hour=4, minute=0),
    },
    "notification_archival": {
        "task": "notifications.archive_old_notifications",
        "schedule": crontab(hour=3, minute=30),  # 3:30 AM UTC daily
    },
    # Recycle bin lifecycle
    "recycle_bin_auto_tombstone": {
        "task": "recycle_bin.tombstone_expired_trash",
        "schedule": crontab(hour=2, minute=30),  # 2:30 AM UTC daily
    },
    "recycle_bin_auto_purge": {
        "task": "recycle_bin.purge_expired_tombstones",
        "schedule": crontab(hour=4, minute=0),  # 4:00 AM UTC daily
    },
    # Self-cleaning demo lifecycle — tear down ACTIVE demo accounts whose TTL
    # has expired so the demo DB doesn't accumulate stale workspaces.
    "demo_accounts_cleanup_expired": {
        "task": "shared_platform.cleanup_expired_demo_accounts",
        "schedule": crontab(hour=3, minute=30),  # 3:30 AM UTC daily
    },
    # AI chat quota windows — daily messages reset at midnight UTC,
    # monthly tokens reset on the 1st. The increment path also handles
    # rollover defensively, so missing one cycle is non-fatal.
    "ai_usage_reset_daily": {
        "task": "ai.reset_daily_ai_usage_windows",
        "schedule": crontab(hour=0, minute=5),  # 00:05 UTC daily
    },
    "ai_usage_reset_monthly": {
        "task": "ai.reset_monthly_ai_usage_windows",
        "schedule": crontab(hour=0, minute=10, day_of_month=1),  # 00:10 UTC on day 1
    },
}
