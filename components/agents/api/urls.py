"""
Agents Bounded Context API URLs

Agent lifecycle, execution, engagement, conversations, memories, and
AI findings (Kanban tasks).

Engagement actions (follow, like, rate, comment, share) are detail actions
on AgentViewSet, generating paths like /agents/{pk}/follow/.

Registration order matters: more-specific agent sub-prefixes are registered
before the general 'agents' prefix to prevent the detail route's {pk}
capture from swallowing /agents/shared/, /agents/executions/, etc.
AgentViewSet also restricts lookup_value_regex to UUIDs as a second safeguard.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from components.agents.api import controller

# Namespace for ``reverse("agents:<url-name>", ...)`` lookups. The
# integration tests under ``components/agents/tests/integration/``
# call ``reverse("agents:follow-agent", ...)``, ``reverse("agents:
# list-agent-executions", ...)``, etc., and require ``agents`` to be
# a registered URL namespace. ``api/urls.py`` includes this module
# at ``ai/`` without an explicit ``namespace=`` argument, so Django
# derives the namespace from ``app_name`` here automatically.
# Restored 2026-06-08 — the pre-deploy gate audit found six tests
# broken by its absence.
app_name = "agents"

# ── Router Setup ──
router = DefaultRouter()

# Register more-specific agent sub-prefixes FIRST to avoid route shadowing.
router.register(r'agents/shared', controller.SharedAgentViewSet, basename='shared-agent')
router.register(r'agents/executions', controller.AgentExecutionViewSet, basename='agent-execution')
router.register(r'agents/runs', controller.DeepRunViewSet, basename='agent-deep-run')
router.register(r'agents/teammate', controller.TeammateViewSet, basename='teammate')

# General agent prefix (detail route restricted to UUID pk)
router.register(r'agents', controller.AgentViewSet, basename='agent')

# Other ViewSets
router.register(r'conversations', controller.ConversationViewSet, basename='conversation')
router.register(r'chat', controller.ChatViewSet, basename='chat')
router.register(r'chains', controller.ChainViewSet, basename='chain')
router.register(r'memories', controller.MemoryViewSet, basename='memory')
router.register(r'health', controller.HealthViewSet, basename='health')
# Canonical read surface for AI findings (Kanban tasks) — replaces the
# deleted ``/ai/actions/`` endpoint per Phase 5 of the
# Agents-as-Teammates migration.
router.register(r'findings', controller.AIFindingsViewSet, basename='ai-findings')
# Wave 4 of the prompt-evaluation plan — read-only API over
# docs/eval-reports/*.json so the V2 HudPromptQualityPanel can render
# without filesystem access.
router.register(
    r'prompt-eval/reports',
    controller.PromptEvalReportsViewSet,
    basename='prompt-eval-reports',
)

# ── URL Patterns ──
urlpatterns = [
    path('', include(router.urls)),
]
