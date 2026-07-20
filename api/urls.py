from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularRedocView, SpectacularSwaggerView

from components.notifications.api.controller import UserPreferenceDetailView, UserPreferenceView
from components.shared_platform.api.urls import (
    broadcast_urlpatterns,
    core_urlpatterns,
    documents_urlpatterns,
    honeypot_urlpatterns,
    imports_urlpatterns,
    uploads_urlpatterns,
)
from components.workspace.api.controller import (
    CountryByNameView,
    CountryDetails,
    CountryListView,
)
from infrastructure.api.health.views import CeleryHealthView, LivenessView
from infrastructure.api.mcp.views import MCPView
from infrastructure.api.schema_views import V1SpectacularAPIView

# ── Infrastructure routes (root-only, never versioned) ───────────────
# Admin, schema/Swagger/Redoc, MCP, health, i18n. These are not part of
# the public API contract, so they are mounted once at the root and are
# NOT exposed under /api/vN/.
infra_patterns = [
    path("octopus/", admin.site.urls),
    path("admin/", include((honeypot_urlpatterns, "admin_honeypot"))),
    # /api/schema/ generates the canonical /api/v1/ surface (api_version='v1').
    # Swagger + Redoc + MCP all consume this view's output. DEFAULT_VERSION
    # ('v0') is untouched — this only pins schema GENERATION, not dispatch.
    path("api/schema/", V1SpectacularAPIView.as_view(), name="schema"),
    path("", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("mcp/", MCPView.as_view(), name="mcp"),
    path("api/health/", LivenessView.as_view(), name="liveness-health"),
    path("api/health/celery/", CeleryHealthView.as_view(), name="celery-health"),
    path("i18n/", include("django.conf.urls.i18n")),
]

# ── Bounded-context API routes (dual-mounted) ────────────────────────
# These carry the public API contract. They are mounted twice (below):
#   * at the root            (/sponsorship/…)        — backward-compatible
#                                                       alias; resolves to
#                                                       request.version='v0'
#   * under /api/(?P<version>vN)/ (/api/v0/sponsorship/…) — explicitly
#                                                       versioned (today: v0)
# Versioning is a primary-adapter concern: the version dimension is
# introduced ONLY here, never in a context urls.py / controller / use
# case. See the `api-versioning` skill + ADR 0006.
# auto-sec fork: only the kept-context routes remain. The nonprofit
# surface (budget/sponsorship/grants/commerce/content/social/etc.) was removed.
api_patterns = [
    path("upload/", include(uploads_urlpatterns)),
    path("imports/", include(imports_urlpatterns)),
    path("documents/", include(documents_urlpatterns)),
    path("identity/", include("components.identity.api.urls")),
    path("userpreferences/", UserPreferenceView.as_view()),
    path("userpreferences/<str:uuid>/", UserPreferenceDetailView.as_view()),
    path("notifications/", include("components.notifications.api.urls")),
    path("feature-flags/", include(core_urlpatterns)),
    path("workspaces/", include("components.workspace.api.urls")),
    path("team/", include("components.team.api.urls")),
    path("membership/", include("components.membership.api.urls")),
    path("project/", include("components.project.api.urls")),
    path("messaging/", include("components.messaging.api.urls")),
    path("social/", include("components.social.api.urls")),
    path("content/", include("components.content.api.urls")),
    path("integrations/", include("components.integrations.api.urls")),
    re_path(r"^countries/ctry/(\w{0,50})", CountryDetails.as_view()),
    path("countries/", CountryListView.as_view()),
    path("countries/<str:country>/", CountryByNameView.as_view()),
    path("audit/", include("components.audit.api.urls")),
    path("search/", include("components.search.api.urls")),
    path("ai/", include("components.agents.api.urls")),
    path("ai/", include("components.knowledge.api.urls")),
    path("announcements/", include(broadcast_urlpatterns)),
    path("sign-off/", include("components.sign_off.api.urls")),
    path("recycle-bin/", include("components.recycle_bin.api.urls")),
    path("templates/", include("components.templates.api.urls")),
]

common_patterns = (
    infra_patterns
    + api_patterns
    + [
        # Explicitly-versioned surfaces. URLPathVersioning reads the <version>
        # kwarg (-> request.version); the unversioned api_patterns above resolve
        # to DEFAULT_VERSION ('v0').
        #
        # The FULL api surface is mounted under the root, /api/v0/, AND /api/v1/ —
        # so EVERY endpoint (all CRUD, every context) resolves under each prefix.
        # v0 = today's organic shape (no stability promise). v1 = the committed
        # contract: read controllers upgrade their response shape when
        # request.version == 'v1' (via serializer_for_version(...) in their
        # mappers/rest); writes and not-yet-upgraded reads pass through with
        # identical v0 behaviour. Mounting the whole surface (rather than a curated
        # allow-list) is what lets the frontend adopt /api/v1/ wholesale once the
        # money-bearing read shapes are migrated. See ADR 0006 + the api-versioning
        # skill.
        re_path(
            r"^api/(?P<version>v0)/",
            include((api_patterns, "v0"), namespace="v0"),
        ),
        re_path(
            r"^api/(?P<version>v1)/",
            include((api_patterns, "v1"), namespace="v1"),
        ),
    ]
)

# If DEBUG is True, include the debug_toolbar URLs
if settings.DEBUG:
    import debug_toolbar

    common_patterns.insert(0, path("__debug__/", include(debug_toolbar.urls)))

if settings.DEBUG:
    common_patterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Serve static and media files during development
urlpatterns = common_patterns + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
