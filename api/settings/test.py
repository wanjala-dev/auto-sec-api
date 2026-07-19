"""Django settings tailored for the pytest suite.

These settings avoid dependencies on external infrastructure (Postgres, Redis,
SMTP, etc.) so the test suite can run with an in-memory/barebones stack.
"""

from __future__ import annotations

import os
from pathlib import Path

# Provide deterministic API keys so modules that eagerly instantiate SDK clients
# during import (e.g. LangChain embeddings) do not fail inside the test suite.
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("OPEN_AI_SECRET_KEY", "test-openai-key")

from .base import *  # noqa: F403 - import base defaults

# Strip out integrations that require external services during the test run.
INSTALLED_APPS = [
    app for app in INSTALLED_APPS if app != "django_elasticsearch_dsl"  # type: ignore[name-defined]
]


# --- Core paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# --- Security / host configuration ---------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "test-secret-key")
SUPER_USER_PASSWORD = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "test-password")

DEBUG = True
ALLOWED_HOSTS = ["*"]
SITE_ID = 1


# --- Static & media -------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static-test"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "test-media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
STATIC_ROOT.mkdir(parents=True, exist_ok=True)

# Use Django's filesystem storages for tests to keep IO local.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


# --- Databases ------------------------------------------------------------------
TEST_DB_DIR = BASE_DIR / ".pytest-dbs"
TEST_DB_DIR.mkdir(exist_ok=True)

def _sqlite_db(name: str) -> dict:
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": TEST_DB_DIR / f"{name}.sqlite3",
    }


DATABASES = {
    "default": {
        **_sqlite_db("default"),
        # SERIALIZE=False skips Django's per-test in-memory JSON serialization of
        # the initial DB state. That serialization only matters for
        # TransactionTestCase with serialized_rollback=True; we don't use it.
        # Shaves 1-3s per pytest invocation; bigger across fix-loop iterations.
        "TEST": {"SERIALIZE": False},
    },
    # In production we use multiple database aliases, but tests should not pay the
    # cost (or risk) of migrating and maintaining multiple independent sqlite DBs.
    #
    # Instead, mirror all secondary aliases to `default` so code paths that call
    # `.using("<alias>")` still work while sharing a single physical database.
    "workspace": {
        **_sqlite_db("workspace"),
        "TEST": {"MIRROR": "default"},
    },
    "art": {
        **_sqlite_db("art"),
        "TEST": {"MIRROR": "default"},
    },
    "ltg": {
        **_sqlite_db("ltg"),
        "TEST": {"MIRROR": "default"},
    },
}

# For tests we don't need tenant-aware routing; route everything to the default
# sqlite database.
DATABASE_ROUTERS = []


# --- Caches ---------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Minimal Elasticsearch DSL configuration so django-elasticsearch-dsl initialises
# without needing a live cluster.
ELASTICSEARCH_DSL = {
    "default": {
        "hosts": "http://localhost:9200",
        "http_auth": None,
        "verify_certs": False,
        "timeout": 5,
    }
}
ELASTICSEARCH_DSL_AUTOSYNC = False


# --- Email ----------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_HOST = "localhost"
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
EMAIL_PORT = 1025
DEFAULT_EMAIL_FROM = "test@example.com"


# --- Celery ---------------------------------------------------------------------
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True


# --- External service placeholders ---------------------------------------------
LOCALHOST_FRONTEND_URL = "http://localhost:3000"

STRIPE_PUBLISHABLE_KEY = ""
STRIPE_SECRET_KEY = ""
STRIPE_BASIC_PRICE_ID = None
STRIPE_PRO_PRICE_ID = None
STRIPE_SPONSOR_MONTHLY_PRICE_ID = None
STRIPE_SPONSOR_YEARLY_PRICE_ID = None
STRIPE_DEFAULT_CURRENCY = "usd"
STRIPE_WEBHOOK_KEY = ""
STRIPE_CONNECT_WEBHOOK_SECRET = ""
STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET = ""
STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET = ""
SUBSCRIPTION_WEBHOOK_URL = ""
WORKSPACE_BILLING_WEBHOOK_URL = ""

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
    }
]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPEN_AI_SECRET_KEY = os.environ["OPEN_AI_SECRET_KEY"]

ELASTICSEARCH_PASSWORD = ""
ELASTICSEARCH_HOST = "localhost"

EMAIL_CLICK_REDIRECT_LINK = None
EMAIL_CONFIRMATION_REDIRECT_PATH = "/identity/email-confirmed"

ART_API_URL = "http://localhost/art"
LTG_API_URL = "http://localhost/ltg"
WORKSPACE_API_URL = "http://localhost/workspaces"


# --- CORS -----------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False


# --- Logging --------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}


# --- Miscellaneous --------------------------------------------------------------
# Keep migrations fast in tests by using the fast password hasher.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]


# --- Realtime / Channels --------------------------------------------------------
# Tests use the in-memory channel layer (no Redis dependency) and the
# NoOp realtime publisher (so signal bridges that fire don't try to
# reach the channel layer when they aren't asserting on it).
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
REALTIME_EVENTS_ENABLED = False


# --- Timezones ------------------------------------------------------------------
# Override base.py's USE_TZ=False. Production code stores datetimes via
# ``django.utils.timezone.now()`` which returns tz-aware values — SQLite
# (the test backend) rejects tz-aware datetimes when USE_TZ=False, which
# masked real bugs in 8+ tool tests under
# ``components/agents/tests/integration/`` and the sharing share-link /
# active-shares suites. Flipping to True so tests exercise the same
# tz-aware path production uses.
USE_TZ = True
