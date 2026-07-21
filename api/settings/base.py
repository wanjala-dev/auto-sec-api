import os

# Keep filesystem paths absolute so template resolution never depends on process CWD.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARENT_BASE_DIR = os.path.dirname(BASE_DIR)


# ── PgBouncer / connection-pooling helpers ───────────────────────────────────
# Shared by prod.py and local.py (both `from .base import *`). The app talks to
# PgBouncer in transaction mode; these helpers apply the two adjustments that
# mode requires, both gated on env vars so a non-pooled deploy is unaffected.
# See the /sql skill for the full rationale.


def _env_truthy(value):
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def apply_pgbouncer_settings(databases):
    """Mutate a Django DATABASES dict for PgBouncer transaction-mode pooling.

    - ``DB_PGBOUNCER=true`` → set ``DISABLE_SERVER_SIDE_CURSORS=True`` on every
      Postgres alias. Transaction pooling hands a server connection back after
      each transaction, so a server-side cursor opened in one transaction would
      be gone in the next. Django then streams ``.iterator()`` client-side in
      chunks — correct, just not server-streamed.
    - ``DB_USE_DIRECT=true`` → repoint HOST/PORT at the real Postgres
      (``DB_DIRECT_HOST``/``DB_DIRECT_PORT``, default ``db:5432``) so migrations
      and other management commands bypass the pooler entirely. Schema changes
      and any future session-scoped migration logic stay on a dedicated,
      session-mode connection rather than a multiplexed transaction-mode one.

    Returns the same dict (mutated in place) for call-site convenience.
    """
    pgbouncer = _env_truthy(os.environ.get("DB_PGBOUNCER"))
    use_direct = _env_truthy(os.environ.get("DB_USE_DIRECT"))
    direct_host = os.environ.get("DB_DIRECT_HOST", "db")
    direct_port = os.environ.get("DB_DIRECT_PORT", "5432")

    for config in databases.values():
        if config.get("ENGINE") != "django.db.backends.postgresql":
            continue
        if pgbouncer:
            config["DISABLE_SERVER_SIDE_CURSORS"] = True
        if use_direct:
            config["HOST"] = direct_host
            config["PORT"] = direct_port
    return databases


TEMPLATE_DIRS = list(
    dict.fromkeys(
        [
            os.path.join(BASE_DIR, "static_templates"),
            os.path.join(BASE_DIR, "templates"),
            os.path.join(BASE_DIR, "client", "templates"),
            os.path.join(PARENT_BASE_DIR, "static_templates"),
            os.path.join(PARENT_BASE_DIR, "templates"),
            os.path.join(PARENT_BASE_DIR, "client", "templates"),
        ]
    )
)

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Application definition
INSTALLED_APPS = [
    # Daphne MUST come before django.contrib.staticfiles so Channels'
    # ASGI runserver replaces the default. See Channels docs.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.flatpages",
    # Realtime — Channels for WebSocket transport (Phase 7+8 of the
    # Real-Time Observability Plan).
    "channels",
    # shared/core dependencies (load first to avoid duplicate model registration)
    "infrastructure.persistence.core",
    "infrastructure.persistence.utils",
    "infrastructure.persistence.audit",
    "infrastructure.persistence.countries",
    "infrastructure.persistence.users",
    "infrastructure.persistence.users.otp",
    "infrastructure.persistence.uploads",
    "infrastructure.persistence.imports",
    "infrastructure.persistence.notifications",
    "infrastructure.persistence.notifications.userpreferences",
    "infrastructure.persistence.workspaces",
    "infrastructure.persistence.workspaces.workflows",
    # Security domains (generalized 'sector') a workspace operates across.
    "infrastructure.persistence.domains",
    # Security report templates — the report-writing kind of the Template Kernel.
    "infrastructure.persistence.security_templates",
    # SaaS billing — subscription tiers/pricing. The org payment/billing ledger
    # models (PaymentMethod/Plan/Event/Order/…) live under the `workspaces` app
    # (imported via workspaces/models.py), NOT as separate apps.
    "infrastructure.persistence.subscription",
    "infrastructure.persistence.team",
    "infrastructure.persistence.social_auth",
    "infrastructure.persistence.broadcast",
    "infrastructure.persistence.project",
    "infrastructure.persistence.messaging",
    "infrastructure.persistence.social",
    "infrastructure.persistence.content",
    "infrastructure.persistence.integrations",
    "infrastructure.persistence.ai",
    "infrastructure.persistence.recycle_bin",
    # ai submodules
    "infrastructure.persistence.ai.aggregations",
    "infrastructure.persistence.ai.callbacks",
    "infrastructure.persistence.ai.chains",
    "infrastructure.persistence.ai.conversations",
    "infrastructure.persistence.ai.embeddings",
    "infrastructure.persistence.ai.llms",
    "infrastructure.persistence.ai.memories",
    "infrastructure.persistence.ai.tracing",
    "infrastructure.persistence.ai.vector_stores",
    "infrastructure.persistence.management_commands",
    "infrastructure.persistence.honeypot",
    "infrastructure.persistence.prompt_eval",
    # Primary adapter CLI apps (management commands + ready() wiring)
    "components.agents.cli",
    "components.shared_platform.cli",
    "components.workspace.cli",
    "components.integrations.cli",
    "components.project.cli",
    "components.identity.cli",
    "components.knowledge.cli",
    "components.workflow.cli",
    "components.sign_off.cli",
    # SaaS billing CLI/ready() wiring (subscription tiers + payments/Stripe).
    "components.subscription.cli",
    "components.payments.cli",
    # libs
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "dj_rest_auth.registration",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_hotp",
    "django_otp.plugins.otp_static",
    "django_celery_results",
    "django_celery_beat",
    "django_elasticsearch_dsl",
    "widget_tweaks",
    "haystack",
    "treebeard",
    "django_tables2",
    "sorl.thumbnail",
    "easy_thumbnails",
    "django_rest_passwordreset",
    "rest_framework.authtoken",
    "dj_rest_auth",
    "crispy_forms",
    "django_filters",
    "markdown",
    "corsheaders",
    "modelcluster",
    "django_seed",
    "drf_spectacular",
    "djmoney",
]

# ── Money / currency configuration ─────────────────────────────────
# The money bounded context is the single source of truth for supported
# currencies (SaaS pricing + billing). djmoney reads CURRENCIES /
# CURRENCY_CHOICES from settings at import time.
from components.money.domain.currencies import (  # noqa: E402
    DEFAULT_CURRENCY as _MONEY_DEFAULT_CURRENCY,
)
from components.money.domain.currencies import (
    SUPPORTED_CURRENCIES as _MONEY_SUPPORTED_CURRENCIES,
)

CURRENCIES = tuple(sorted(_MONEY_SUPPORTED_CURRENCIES))
CURRENCY_CHOICES = [(code, code) for code in CURRENCIES]
DEFAULT_CURRENCY = _MONEY_DEFAULT_CURRENCY

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Required by django-allauth since 0.63 on Django 5+
    "allauth.account.middleware.AccountMiddleware",
    "components.notifications.infrastructure.adapters.platform_middleware.CurrentActorMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.flatpages.middleware.FlatpageFallbackMiddleware",
    "components.shared_platform.infrastructure.middleware.tenant_middlewares.TenantMiddleware",
    # Stamps RFC 9745/8594 deprecation headers on deprecated API versions.
    # Dormant until API_DEPRECATED_VERSIONS (below) is populated. See the
    # `api-versioning` skill §8 + ADR 0006.
    "components.shared_platform.infrastructure.middleware.api_deprecation_middleware.ApiDeprecationMiddleware",
    # Pops the URL-path `version` kwarg out of the view kwargs (stashing it on
    # the request) so the full surface mounted under /api/vN/ doesn't pass an
    # unexpected `version=` keyword to rigid view handler signatures. Paired
    # with RequestStashURLPathVersioning (DEFAULT_VERSIONING_CLASS) which reads
    # the version from that stash. See ADR 0006 + infrastructure/api/versioning.py.
    "infrastructure.api.versioning.StripVersionKwargMiddleware",
]

# Single-DB fork — the multi-tenant DB router was dropped. All models route to
# `default`. (Row-level workspace scoping stays in the ORM queries.)
DATABASE_ROUTERS = []

HAYSTACK_CONNECTIONS = {
    "default": {
        "ENGINE": "haystack.backends.solr_backend.SolrEngine",
        "URL": "http://127.0.0.1:8983/solr",
        "INCLUDE_SPELLING": True,
    },
}


SPECTACULAR_SETTINGS = {
    "TITLE": "Wanjala API v2",
    "DESCRIPTION": "wanjala api",
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # When enabled, drf-spectacular won't emit warnings/errors for endpoints
    # that are hard to introspect (e.g., APIView without serializer_class).
    # This is useful to reduce log noise when /api/schema/ is fetched for MCP.
    "DISABLE_ERRORS_AND_WARNINGS": os.getenv("SPECTACULAR_DISABLE_ERRORS_AND_WARNINGS", "false").lower()
    in {"1", "true", "yes"},
    "ENUM_NAME_OVERRIDES": {
        "TriggeredByEnum": "reports.models.FinancialReport.TRIGGER_CHOICES",
    },
    # Strip the `/api/vN` version prefix from operationId generation so a
    # versioned operation gets the SAME path-derived operationId it had at the
    # unversioned root (e.g. `/api/v1/sponsorship/donations/my/` →
    # `sponsorship_donations_my_retrieve`, not `api_v1_…`/`v1_…`). Pinning the
    # prefix makes this deterministic rather than leaning on drf-spectacular's
    # data-dependent common-path estimation (which would otherwise strip `/api/`
    # and mangle infra ops like `api_health_retrieve` → `health_retrieve` when
    # every published path moves under `/api/v1/`). Infra routes (`/api/health/`)
    # don't match `/api/vN` and keep their `api_…` operationId, exactly as today.
    # ContextualAutoSchema.get_operation_id additionally strips any residual
    # `(api_)?vN_` token as a backstop. See the `api-versioning` skill §5.
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    # Publish /api/v1/ as the canonical schema surface (Swagger + Redoc + MCP
    # tools). The hook keeps the versioned (/api/{version}/…) endpoints and
    # drops the root-alias duplicates; the schema view generates with
    # api_version='v1', so {version} renders as v1. operationIds stay
    # version-independent via ContextualAutoSchema.get_operation_id, so MCP
    # tool names are unchanged across the cutover. See the `api-versioning`
    # skill §5/§8 + ADR 0006.
    "PREPROCESSING_HOOKS": [
        "infrastructure.api.schema_hooks.keep_only_canonical_v1_paths",
    ],
    # OTHER SETTINGS
}


ROOT_URLCONF = "api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": TEMPLATE_DIRS,
        "OPTIONS": {
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.request",
                "django.template.context_processors.debug",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.contrib.messages.context_processors.messages",
            ],
            #'debug': DEBUG,
        },
    }
]

WSGI_APPLICATION = "api.wsgi.application"
ASGI_APPLICATION = "api.asgi.application"

# ── Channels / WebSocket (Phase 7+8 of the Real-Time Observability Plan) ──
#
# Default channel layer points at Redis (the same instance used by
# Celery + Django cache). Per-environment settings override
# ``CHANNEL_LAYERS["default"]["CONFIG"]["hosts"]`` if the prod URL
# differs. Tests override to in-memory or NoOp to avoid needing
# Redis in CI.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_URL", "redis://redis:6379/0")],
        },
    }
}

# Toggle for opting individual environments out of realtime publishing
# (one-shot CLI scripts, integration test runs, dev without Redis).
# When False, ``RealtimeEventProvider`` returns the NoOp adapter so
# every ``publish`` call is a silent no-op.
REALTIME_EVENTS_ENABLED = True

# Realtime leg of the notification dispatcher funnel (badge/feed live
# updates over /ws/notifications/). Independent of REALTIME_EVENTS_ENABLED
# so notification streaming can be toggled without silencing agent-run /
# sponsor-feed events (and vice versa). RealtimeNotificationChannel
# no-ops when False.
NOTIFICATIONS_REALTIME_ENABLED = os.environ.get("NOTIFICATIONS_REALTIME_ENABLED", "true").lower() == "true"

# Web push (registry + delivery ledger; pywebpush sender). All env-driven,
# default empty/off — the registry accepts subscriptions and the ledger
# records pending deliveries either way; WEB_PUSH_ENABLED flips the actual
# sender on once VAPID keys are provisioned. Missing keys degrade to a
# truthful "skipped" delivery, never a crash.
WEB_PUSH_ENABLED = os.environ.get("WEB_PUSH_ENABLED", "false").lower() == "true"
WEBPUSH_VAPID_PUBLIC_KEY = os.environ.get("WEBPUSH_VAPID_PUBLIC_KEY", "")
WEBPUSH_VAPID_PRIVATE_KEY = os.environ.get("WEBPUSH_VAPID_PRIVATE_KEY", "")
WEBPUSH_VAPID_ADMIN_EMAIL = os.environ.get("WEBPUSH_VAPID_ADMIN_EMAIL", "")

# Email notification channel. Same safe-dormant pattern as WEB_PUSH_ENABLED:
# the dispatch funnel records pending email ledger rows for opted-in users
# either way; this flag flips the actual sender on. Off by default so no
# environment sends emails until ops explicitly enables it.
NOTIF_EMAIL_CHANNEL_ENABLED = os.environ.get("NOTIF_EMAIL_CHANNEL_ENABLED", "false").lower() == "true"

AUTH_USER_MODEL = "users.CustomUser"

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "components.identity.infrastructure.adapters.zxcvbn_password_validator.ZxcvbnPasswordValidator",
    },
]

# Minimum zxcvbn score (0-4). 3 = strong enough to resist online attacks.
PASSWORD_MINIMAL_STRENGTH = 3


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/
DEFAULT_CHARSET = "utf-8"

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = False

CRISPY_TEMPLATE_PACK = "bootstrap4"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "NON_FIELD_ERRORS_KEY": "error",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        #'rest_framework.authentication.TokenAuthentication',
        #'rest_framework.authentication.SessionAuthentication', #enable rest auth use for dev
        #'rest_framework.authentication.BasicAuthentication',
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        #'rest_framework.permissions.AllowAny',
        "rest_framework.permissions.IsAdminUser",
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "200/minute",
        "user": "1000/minute",
        "workflow_runs": "120/min",
        "workflow_steps": "300/min",
        "blog-categories": "1000/day",
        "photos-categories": "1000/day",
        "videos-categories": "1000/day",
        "paintings-categories": "1000/day",
        "auth_login": "10/min",
        "auth_password_reset_request": "5/hour",
        "auth_password_reset_confirm": "10/hour",
        "auth_email_verify": "15/hour",
        # Payment endpoints
        "checkout_anon": "20/min",
        "checkout_user": "30/min",
        "payment_webhook": "200/min",
        "donation_anon": "15/min",
        # Newsletter public endpoints. Subscribe is 5/min/IP to slow
        # email-enumeration attacks. Unsubscribe is looser at 30/min
        # because subscribers retry clicks + email clients prefetch
        # links. SNS handler is generous — SES retries up to ~50 times
        # per notification on transient failures.
        "newsletter_subscribe_anon": "5/min",
        "newsletter_unsubscribe_anon": "30/min",
        # Open-pixel loads burst (Apple MPP prefetches every recipient's
        # pixel at delivery) — the handler is one indexed row update.
        "newsletter_open_pixel_anon": "300/min",
        "sns_webhook": "200/min",
        # Public pre-auth login-brand lookup (anonymous, keyed on workspace id).
        "workspace_login_brand": "60/min",
    },
    "DEFAULT_SCHEMA_CLASS": "infrastructure.api.schema.ContextualAutoSchema",
    "EXCEPTION_HANDLER": "infrastructure.api.exception_handler.custom_exception_handler",
    # ── API versioning (URL path: /api/vN/) ──────────────────────────
    # The version is a path segment. The API has never been formally
    # versioned, so today's organic surface is honestly **v0** (semver
    # "no stability promise"), NOT v1. `v1` is reserved for the first
    # version we deliberately design and commit to. Legacy unversioned
    # routes (mounted at the root in api/urls.py for backward compat)
    # carry no `version` kwarg, so they resolve to DEFAULT_VERSION = 'v0'.
    # Nothing in the core branches on request.version — versioning is a
    # primary-adapter concern that lives ONLY in api/ + mappers/rest/.
    # See the `api-versioning` skill and ADR 0006.
    #
    # RequestStashURLPathVersioning is URLPathVersioning that reads the version
    # from request.url_path_version (set by StripVersionKwargMiddleware, which
    # pops the `version` URL kwarg before it reaches the view) instead of from
    # the view kwargs. This lets the FULL surface mount under /api/vN/ without
    # every rigid view handler needing **kwargs to absorb `version=`. See
    # infrastructure/api/versioning.py.
    "DEFAULT_VERSIONING_CLASS": "infrastructure.api.versioning.RequestStashURLPathVersioning",
    "DEFAULT_VERSION": "v0",
    "ALLOWED_VERSIONS": ["v0", "v1"],
    "VERSION_PARAM": "version",
}


# ── API version deprecation (RFC 9745 Deprecation + RFC 8594 Sunset) ──
# Maps an API version -> its deprecation/sunset schedule. ApiDeprecationMiddleware
# stamps the RFC 9745 `Deprecation` + RFC 8594 `Sunset` + a migration-guide `Link`
# on every response served by a version listed here — covering BOTH the explicit
# `/api/v0/` mount AND the unversioned root alias (both serve the v0 contract).
# `sunset` MUST be >= `deprecation`. See the `api-versioning` skill §8 + ADR 0006.
#
# v0 is the organic, never-committed surface (no stability promise); v1 is the
# committed contract and the successor. Phase 3 of the versioning roadmap
# announces v0's deprecation here with a 12-month sunset window (2026-06-19 →
# 2027-06-19). After the sunset date, v0 is slated to return 410 Gone (Phase 4).
API_DEPRECATED_VERSIONS: dict = {
    "v0": {
        "deprecation": "2026-06-19T00:00:00Z",
        "sunset": "2027-06-19T00:00:00Z",
        "successor": "/api/v1/",
        "link": "https://github.com/wanjala-dev/api-v0.2.0/blob/development/api-v2.0/docs/api/migrating-v0-v1.md",
    },
}


INTERNAL_IPS = [
    "127.0.0.1",
]

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

LOGIN_RESPONSE_MODE = "legacy"
SECURITY_EVENTS_ASYNC = True

LOGIN_REDIRECT_URL = "post-list"
ACCOUNT_EMAIL_REQUIRED = True
REST_SESSION_LOGIN = False
REST_USE_JWT = True
AUTH_USER_MODEL = "users.CustomUser"

# Customer-facing brand name. Used in transactional email subjects, preheaders,
# and template bodies — kept separate from the Django Site `domain`/`name` (which
# encode the API host, e.g. "api.wanjala.art") so the brand never leaks the API
# URL to end users.
SITE_NAME = os.environ.get("SITE_NAME", "Auto-Sec")

# Recipients for landing "Contact Us" inquiry notifications (comma-separated).
# Every contact-form submission emails a copy of the inquiry to each address
# (in addition to the visitor's thank-you email). One Celery task is
# dispatched per recipient so each send retries independently.
CONTACT_NOTIFICATION_EMAILS = [
    a.strip()
    for a in os.environ.get(
        "CONTACT_NOTIFICATION_EMAILS",
        "octopus.ai.intl@gmail.com,c0d3henry@gmail.com",
    ).split(",")
    if a.strip()
]

# Sender identity for both landing contact-form emails (visitor thank-you +
# owner notification). MUST be an SES-verified identity — the octopusintl.org
# domain identity is verified in us-east-1, which covers this default. RFC 5322
# display-name form ("Auto-Sec <addr>") so inboxes show "Auto-Sec", not "info";
# matches the DEFAULT_FROM_EMAIL default in local.py/prod.py. Falls back to
# DEFAULT_FROM_EMAIL in the controller when set empty.
CONTACT_FROM_EMAIL = os.environ.get("CONTACT_FROM_EMAIL", "Auto-Sec <info@octopusintl.org>")

# Use pytest (via runner.PytestTestRunner) for Django's test command.
TEST_RUNNER = "runner.PytestTestRunner"

# ── Financial report PDF rendering ─────────────────────────────────────
# ``REPORT_PDF_RENDERER`` picks which adapter the provider hands back:
#   - "gotenberg" (default)  → HTTP POST to Gotenberg container
#   - "fake"                  → in-memory sentinel bytes, test only
REPORT_PDF_RENDERER = os.environ.get("REPORT_PDF_RENDERER", "gotenberg")
GOTENBERG_URL = os.environ.get("GOTENBERG_URL", "http://gotenberg:3000")
GOTENBERG_TIMEOUT_SECONDS = int(os.environ.get("GOTENBERG_TIMEOUT_SECONDS", "30"))

# ── Report PDF object storage ──────────────────────────────────────────
# In dev we point at MinIO (S3-compatible); in prod we point at real S3.
# The storage helper uses boto3 directly (not django-storages) because
# this bucket is operated outside Django's MEDIA/STATIC surface — it's an
# application bucket keyed by workspace/report uuids, not uploaded files.
REPORT_PDF_BUCKET = os.environ.get("REPORT_PDF_BUCKET", "wanjala-reports")
# Internal endpoint — used by the Django / Celery containers to upload
# PDFs. Points at the Docker-network hostname ``minio:9000`` in dev.
REPORT_PDF_S3_ENDPOINT = os.environ.get("REPORT_PDF_S3_ENDPOINT", "http://minio:9000")
# Public endpoint — used when generating the presigned URL the browser
# follows. In dev this must be host-reachable (the mapped MinIO port).
# In prod both values are the same — real S3 has no split.
REPORT_PDF_S3_PUBLIC_ENDPOINT = os.environ.get(
    "REPORT_PDF_S3_PUBLIC_ENDPOINT",
    os.environ.get("REPORT_PDF_S3_ENDPOINT", "http://localhost:9100"),
)
REPORT_PDF_S3_REGION = os.environ.get("REPORT_PDF_S3_REGION", "us-east-1")
REPORT_PDF_S3_ACCESS_KEY = os.environ.get("REPORT_PDF_S3_ACCESS_KEY", "wanjala")
REPORT_PDF_S3_SECRET_KEY = os.environ.get("REPORT_PDF_S3_SECRET_KEY", "wanjaladev")
REPORT_PDF_S3_PRESIGNED_TTL_SECONDS = int(os.environ.get("REPORT_PDF_S3_PRESIGNED_TTL_SECONDS", "600"))

# Vector store backend used by the RAG pipeline (PDF chunking,
# document embeddings, similarity search). The lean prod stack runs
# without Elasticsearch — pgvector via the existing Postgres + pgvector
# extension is the default. Flip via env var to switch back to ES
# without touching code.
VECTOR_STORE_PROVIDER = os.environ.get("VECTOR_STORE_PROVIDER", "pgvector")

# ── Plaid ──────────────────────────────────────────────────────────────
# https://plaid.com/docs/api/
# Set in .env.production for demo, .env.local for dev. Sandbox mode is
# free — grab sandbox keys at https://dashboard.plaid.com/team/keys.
# When ``PLAID_CLIENT_ID`` / ``PLAID_SECRET`` are blank the Plaid
# bank-feed adapter raises ``BankFeedProviderUnsupportedError`` on first
# use — this is the intentional Phase-2.0 state (no adapter is registered
# yet; the real Plaid adapter lands in PR 2.1).
PLAID_CLIENT_ID = os.environ.get("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.environ.get("PLAID_SECRET", "")
# One of: ``sandbox`` | ``development`` | ``production``. Default stays
# on sandbox so a fresh checkout cannot accidentally hit production Plaid.
PLAID_ENV = os.environ.get("PLAID_ENV", "sandbox")
# Public URL Plaid posts webhook events to. Empty in dev (a tunneled
# callback is used locally); always set on prod.
PLAID_WEBHOOK_URL = os.environ.get("PLAID_WEBHOOK_URL", "")
# Phase-2 v1 ships ``transactions`` only. Phase-4 layers ``income`` on
# top for the income-verification port.
PLAID_PRODUCTS = ["transactions"]
PLAID_COUNTRY_CODES = ["US", "CA"]

# ── Login-session enrichment + retention ──────────────────────────────
# Directory holding MaxMind GeoLite2 databases. The adapter reads
# ``<GEOIP_PATH>/GeoLite2-City.mmdb``. The file is OPTIONAL — dev/test/CI
# ship without it and the GeoIP adapter then returns None for every
# lookup (sessions enrich with device facts only, geo columns stay
# blank). Fetch it with ``scripts/fetch_geolite2.sh`` (free MaxMind
# license key required); see ``docs/reference/GEOIP_SETUP.md``.
GEOIP_PATH = os.environ.get("GEOIP_PATH", os.path.join(BASE_DIR, "geoip"))

# Retention windows enforced by the daily ``identity.sweep_user_sessions``
# beat task: dead sessions (revoked/expired) are deleted after
# SESSION_RETENTION_DAYS; AuthAuditEvent rows after AUTH_AUDIT_RETENTION_DAYS.
SESSION_RETENTION_DAYS = int(os.environ.get("SESSION_RETENTION_DAYS", "180"))
AUTH_AUDIT_RETENTION_DAYS = int(os.environ.get("AUTH_AUDIT_RETENTION_DAYS", "365"))

# Push/delivery hygiene windows enforced by the weekly
# ``notifications.prune_stale_push_subscriptions`` beat task: dead
# subscriptions (expired/revoked) are deleted after
# PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS; active subscriptions not seen for
# PUSH_SUBSCRIPTION_STALE_AFTER_DAYS are marked expired (then age into
# the deletion window); terminal NotificationDelivery ledger rows
# are deleted after NOTIFICATION_DELIVERY_RETENTION_DAYS.
PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS = int(os.environ.get("PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS", "90"))
PUSH_SUBSCRIPTION_STALE_AFTER_DAYS = int(os.environ.get("PUSH_SUBSCRIPTION_STALE_AFTER_DAYS", "180"))
NOTIFICATION_DELIVERY_RETENTION_DAYS = int(os.environ.get("NOTIFICATION_DELIVERY_RETENTION_DAYS", "180"))
