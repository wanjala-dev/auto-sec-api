"""Production settings for the Auto-Sec API (api.auto-sec.ai).

Rewritten 2026-08-09 from the wanjala fork-drift version the prod-readiness
review flagged (blocker #5): the old file defaulted the database to the
wanjala compose stack (``DB_HOST=db`` / ``wanjala-api-database``), pointed
CORS/CSRF at octopusintl.org/literacyseed, sent email from
``info@octopusintl.org`` and wrote media uploads into the CROSS-PROJECT
``wanjala-demo-sandbox-data`` bucket. Every one of those universes is gone:

- DB is ``DATABASE_URL``-driven (required, single-DB — autosec dropped the
  tenant router; there are no workspace/art/linkthegap aliases).
- Hosts/CORS/CSRF default to the real prod domains (app/api.auto-sec.ai) and
  stay env-overridable.
- Email defaults to the SES-verified auto-sec.ai identity.
- Media goes to the ``media/`` prefix of ``autosec-prod-data`` via the k3s
  host's instance role (IMDSv2 — no static keys).
- Static files are served by WhiteNoise (there is no nginx sidecar in the k8s
  stack; gunicorn is the only web process).

Secrets/env are injected by the k8s prod overlay (auto-sec-infra
``k8s/overlays/prod`` — rendered from SSM Parameter Store by manage-prod.sh).
"""

import os
from datetime import timedelta

import dj_database_url
import environ
from celery.schedules import crontab
from corsheaders.defaults import default_headers

from infrastructure.celery.routes import TASK_ROUTES

from .base import *  # noqa: F403

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Read environment variables ──────────────────────────────────────────────
env = environ.Env(DEBUG=(bool, False))
env_file = os.path.join(BASE_DIR, ".env")
if os.path.isfile(env_file):
    env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
SITE_ID = 2

# ── Hosts / origins (auto-sec.ai universe; env-overridable) ─────────────────
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", default="api.auto-sec.ai").split(",") if h.strip()]

# FRONTEND_URL is the single source of truth for emailed links — REQUIRED (a
# boot crash beats silently mailing localhost links). LOCALHOST_FRONTEND_URL is
# the legacy name core_utils still reads.
FRONTEND_URL = env("FRONTEND_URL")
LOCALHOST_FRONTEND_URL = env("LOCALHOST_FRONTEND_URL", default=FRONTEND_URL)
EMAIL_CONFIRMATION_REDIRECT_PATH = env("EMAIL_CONFIRMATION_REDIRECT_PATH", default="/identity/email-confirmed")

CORS_ORIGIN_ALLOW_ALL = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in env("CORS_ALLOWED_ORIGINS", default="https://app.auto-sec.ai").split(",") if o.strip()
]
CORS_ALLOW_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]
CORS_ALLOW_HEADERS = list(default_headers) + [
    "cache-control",
    "pragma",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
]

# The Django admin (mounted at /octopus/ — /admin/ is the honeypot) is
# session+CSRF authenticated, so the API origin itself must be trusted too.
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in env("CSRF_TRUSTED_ORIGINS", default="https://api.auto-sec.ai,https://app.auto-sec.ai").split(",")
    if o.strip()
]

# ── Email (AWS SES — the auto-sec.ai SESv2 identity) ────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="email-smtp.us-east-1.amazonaws.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
# celery-tasks skill §3c (backoff ≠ timeout): bound every SMTP/SES send with a
# per-attempt socket timeout so a hung SES connection can't pin a worker slot.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
EMAIL_HOST_USER = env("SES_SMTP_USER", default=env("EMAIL_HOST_USER", default=""))
EMAIL_HOST_PASSWORD = env("SES_SMTP_PASSWORD", default=env("EMAIL_HOST_PASSWORD", default=""))
# Must stay an identity SES has verified — that's no-reply@auto-sec.ai (the
# domain identity lives in auto-sec-infra terraform/workloads/api/ses.tf).
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Auto-Sec <no-reply@auto-sec.ai>")
SERVER_EMAIL = env("SERVER_EMAIL", default="Auto-Sec <no-reply@auto-sec.ai>")
# Address-only form used when stitching "From: {workspace} <addr>" headers, and
# the RFC 8058 List-Unsubscribe mailto slot. NOTE: auto-sec.ai has no inbound
# MX — the unsubscribe mailto is a dead drop until inbound mail exists; the
# one-click HTTPS unsubscribe path is the working one.
EMAIL_FROM = env("EMAIL_FROM", default="no-reply@auto-sec.ai")
EMAIL_UNSUBSCRIBE_MAILTO = env("EMAIL_UNSUBSCRIBE_MAILTO", default="unsubscribe@auto-sec.ai")
# SES bounce + complaint SNS topic ARN — the topic the SES configuration set
# forwards bounces/complaints to. Empty ⇒ the SNS webhook handler rejects ALL
# inbound notifications (safe default: reject rather than trust unverified).
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

# ── AI / LLM ───────────────────────────────────────────────────────────────
LANGFUSE_SECRET_KEY = env("LANGFUSE_SECRET_KEY", default="")
LANGFUSE_PUBLIC_KEY = env("LANGFUSE_PUBLIC_KEY", default="")
LANGFUSE_BASE_URL = env("LANGFUSE_BASE_URL", default="")
OPEN_AI_SECRET_KEY = env("OPEN_AI_SECRET_KEY", default="")

# ── Fork-drift placeholders still read by base settings ─────────────────────
# autosec is single-tenant-DB; these tenant-routing URLs are dead but required
# by inherited code paths. Same placeholders the k8s configmap uses.
ART_API_URL = env("ART_API_URL", default="http://localhost")
LTG_API_URL = env("LTG_API_URL", default="http://localhost")
WORKSPACE_API_URL = env("WORKSPACE_API_URL", default="http://localhost")
EMAIL_CLICK_REDIRECT_LINK = env("EMAIL_CLICK_REDIRECT_LINK", default=FRONTEND_URL)

# ── Strip dev-only / heavy apps not needed in prod ──────────────────────────
# Elasticsearch is replaced by pgvector + PostgreSQL full-text search.
# Haystack is unused (Solr backend, never deployed). django_seed is dev-only.
_EXCLUDED_APPS = {"django_elasticsearch_dsl", "haystack", "django_seed"}
INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in _EXCLUDED_APPS]
HAYSTACK_CONNECTIONS = {}

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

# ── Redis (app-level client; broker config is under Celery below) ───────────
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

# ── Database — DATABASE_URL-driven, single-DB (no tenant aliases) ───────────
# REQUIRED: no default. The old wanjala fallbacks (DB_HOST=db /
# wanjala-api-database / wanjala-art-sql-user) meant a missing env var booted
# the app pointed at a database that doesn't exist in this universe — a boot
# crash on a missing DATABASE_URL is strictly better.
DATABASES = {
    "default": dj_database_url.config(default=env("DATABASE_URL")),
}

# Optional psycopg3 native pooling (Django ignores OPTIONS["pool"] on psycopg2).
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

# PgBouncer transaction-mode adjustments (no-op unless DB_PGBOUNCER /
# DB_USE_DIRECT env vars are set — a direct-to-Postgres deploy is unchanged).
apply_pgbouncer_settings(DATABASES)  # noqa: F405

# ── Static files — WhiteNoise (gunicorn is the only web process) ────────────
# There is no nginx sidecar in the k8s stack and DEBUG=False disables Django's
# static serving, so without WhiteNoise the admin at /octopus/ ships unstyled.
# collectstatic runs at container boot (docker/scripts/prod/start-web.sh);
# the manifest storage gives hashed, immutably-cacheable names.
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"
MIDDLEWARE = (
    MIDDLEWARE[: MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1]  # noqa: F405
    + ["whitenoise.middleware.WhiteNoiseMiddleware"]
    + MIDDLEWARE[MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1 :]  # noqa: F405
)

# ── Media — S3 on the autosec data bucket's media/ prefix ───────────────────
# MEDIA_ROOT stays defined so legacy code paths constructing paths from it get
# something sane (writes actually go to S3 via S3MediaStorage).
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Auth: NO explicit AWS keys. boto3's default chain reaches IMDSv2 and picks up
# the autosec-prod-host instance role (which grants exactly the media/* prefix
# of this bucket — see auto-sec-infra terraform/workloads/api/main.tf).
AWS_STORAGE_BUCKET_NAME = os.environ.get("MEDIA_S3_BUCKET", "autosec-prod-data")
AWS_S3_REGION_NAME = os.environ.get("MEDIA_S3_REGION", "us-east-1")
AWS_LOCATION = os.environ.get("MEDIA_S3_PREFIX", "media")
AWS_S3_ADDRESSING_STYLE = "virtual"
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
# 15 minutes: long enough for one page-load to fetch every image, short enough
# that a leaked URL stops being useful quickly.
AWS_QUERYSTRING_EXPIRE = 60 * 15

# MEDIA_URL is informational once S3 takes over (S3MediaStorage signs real
# URLs); kept sane for any code path still reading it.
MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{AWS_LOCATION}/"

STORAGES = {
    "default": {
        "BACKEND": "infrastructure.storage.backends.S3MediaStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ── Report PDF / SBOM object storage — REAL S3, no split (review §4.5) ──────
# Closes the named follow-up this file used to carry. Reports and SBOMs used to
# target the in-cluster MinIO via base.py's REPORT_PDF_S3_* / SBOM_S3_* defaults,
# which have a DELIBERATE two-endpoint split: an internal origin the app writes
# through, and a public origin the browser follows a presigned URL to. That split
# is correct for dev MinIO (``minio:9000`` means nothing to the viewer's browser)
# and structurally broken for prod, where the public default resolved to
# ``http://localhost:9100`` — a customer clicking "download SBOM" got a URL
# pointing at their OWN laptop. The prod overlay had also deleted the
# ``minio-public`` LoadBalancer, so there was no reachable origin to point at.
#
# Real S3 removes the split rather than papering over it, which is the better
# posture for a security product: nothing about our object store gets exposed to
# the internet, and there is no second origin to keep in sync. Reports and SBOMs
# join media/ and scan-artifacts/ as prefixes of the ONE ``autosec-prod-data``
# bucket (auto-sec-infra terraform/workloads/api/s3.tf).
#
# Endpoint = None on BOTH sides. None (not "") is load-bearing: boto3 treats None
# as "no endpoint override, use the real AWS endpoint", while "" is a malformed
# override. Setting both from one value makes a prod split unrepresentable.
#
# Credentials = None on BOTH keys, which is what makes boto3's default chain fall
# through to IMDSv2 and pick up the k3s host's instance role. Inheriting base.py's
# dev MinIO creds ("wanjala"/"wanjaladev") would 403 every upload against AWS —
# the same trap the scan-artifact channel documents in base.py. Prod has NO static
# S3 keys; the IAM grant is ReportsPrefixRW / SbomsPrefixRW on the host role
# (terraform/workloads/api/main.tf).
REPORT_PDF_BUCKET = env("REPORT_PDF_BUCKET", default="autosec-prod-data")
REPORT_PDF_S3_ENDPOINT = env("REPORT_PDF_S3_ENDPOINT", default="") or None
REPORT_PDF_S3_PUBLIC_ENDPOINT = REPORT_PDF_S3_ENDPOINT
REPORT_PDF_S3_REGION = env("REPORT_PDF_S3_REGION", default="us-east-1")
REPORT_PDF_S3_ACCESS_KEY = None
REPORT_PDF_S3_SECRET_KEY = None
REPORT_PDF_S3_PREFIX = env("REPORT_PDF_S3_PREFIX", default="reports")

SBOM_S3_BUCKET = env("SBOM_S3_BUCKET", default=REPORT_PDF_BUCKET)
SBOM_S3_ENDPOINT = env("SBOM_S3_ENDPOINT", default="") or None
SBOM_S3_PUBLIC_ENDPOINT = SBOM_S3_ENDPOINT
SBOM_S3_REGION = env("SBOM_S3_REGION", default=REPORT_PDF_S3_REGION)
SBOM_S3_ACCESS_KEY = None
SBOM_S3_SECRET_KEY = None
SBOM_S3_PREFIX = env("SBOM_S3_PREFIX", default="sboms")

# ── Celery ──────────────────────────────────────────────────────────────────
CELERY_BEAT_SCHEDULE = {
    # auto-sec fork: nonprofit aggregation/search/payment/budget beats removed.
    # Keep this dict in lockstep with api/settings/local.py — a schedule
    # missing HERE silently disables that pipeline in prod.
    "identity_sweep_user_sessions": {
        "task": "identity.sweep_user_sessions",
        "schedule": crontab(minute="*/15"),
    },
    # Weekly push/delivery hygiene (idempotent reconciliation).
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
    # AI-teammate cycle — the detector fan-out that makes the SOC log-watch →
    # triage pipeline autonomous. Self-gating (ai_teammate_enabled flag,
    # feature.ai_kill_switch, dispatch lease).
    "schedule_ai_teammate_runs": {
        "task": "infrastructure.ai.agents.tasks.schedule_ai_teammate_runs",
        "schedule": crontab(minute="*/5"),
    },
    # Daily AI-action rollup for the governance charts.
    "rollup_ai_action_daily": {
        "task": "ai.rollup_ai_action_daily",
        "schedule": crontab(minute=20, hour=0),
    },
    # Nightly Prowler CSPM scan — dark until opt-in (feature.cloud_posture).
    "schedule_cloud_posture_scans": {
        "task": "cloud_posture.schedule_prowler_runs",
        "schedule": crontab(hour=2, minute=0),
    },
    # Nightly Vercel posture scan (ADR 0021 D3) — dark until opt-in.
    "schedule_vercel_posture_scans": {
        "task": "cloud_posture.schedule_vercel_prowler_runs",
        "schedule": crontab(hour=2, minute=30),
    },
    # Daily Trivy container-SCA rescan — dark until opt-in
    # (feature.container_security). Was MISSING here (fork-drift) while present
    # in local.py — prod would have silently never rescanned images.
    "schedule_container_scans": {
        "task": "container_security.schedule_container_scans",
        "schedule": crontab(hour=3, minute=0),
    },
    # Nightly Opengrep SAST rescan (ADR 0019 D3) — dark until opt-in
    # (feature.code_security). Also previously missing here; same drift class.
    "schedule_repo_scans": {
        "task": "code_security.schedule_repo_scans",
        "schedule": crontab(hour=3, minute=30),
    },
    # Daily threat-intel feed refresh (ADR 0013 D2) — EPSS + CISA KEV.
    "vuln_intel_refresh_feeds": {
        "task": "vuln_intel.refresh_feeds",
        "schedule": crontab(hour=1, minute=30),
    },
    # Hourly Remediation Memory capture reconciler (ADR 0012 P4a).
    "reconcile_applied_remediations": {
        "task": "remediation.reconcile_applied_remediations",
        "schedule": crontab(minute=15),
    },
    # Daily Remediation Memory orphan-recovery sweep (ADR 0012 P6).
    "reindex_remediation_corpus": {
        "task": "remediation.reindex_remediation_corpus",
        "schedule": crontab(hour=3, minute=30),
    },
}

# Routing — NAMESPACE GOTCHA: with config_from_object(namespace="CELERY") only
# NEW-style names apply. Canonical task->queue map lives in
# infrastructure/celery/routes.py; locked by tests/test_celery_task_routes.py.
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = TASK_ROUTES

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
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.environ.get("CELERY_WORKER_PREFETCH_MULTIPLIER", 1))
CELERY_WORKER_MAX_TASKS_PER_CHILD = int(os.environ.get("CELERY_WORKER_MAX_TASKS_PER_CHILD", 50))
CELERY_RESULT_EXPIRES = int(os.environ.get("CELERY_RESULT_EXPIRES", 3600))
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# ── Security headers / TLS (NGF terminates TLS and sets X-Forwarded-Proto) ──
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
