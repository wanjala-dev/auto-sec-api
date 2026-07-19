"""Architecture guardrail: controllers must not import ORM models directly.

Controllers in ``components/*/api/`` are presentation-layer adapters.
They should delegate business operations through application services,
providers, or facades — never directly query/modify ORM models.

This test flags controllers that import from ``apps.*.models`` or
``django.db`` (excluding ``django.db.models`` usage in serializer
Meta classes, which is a DRF presentation concern handled via a
separate allowlist).

The cross-context and concrete-adapter tests in
``test_cross_context_import_rules.py`` already cover
``components.*.infrastructure.*`` imports.  This test covers the
remaining gap: direct ``apps.*.models`` usage.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# Known bounded contexts
_CONTEXTS = sorted(
    d.name
    for d in COMPONENTS_DIR.iterdir()
    if d.is_dir() and (d / "__init__.py").exists() and d.name != "shared_kernel"
)

# ── Transitional allowlist ───────────────────────────────────────────
# Controllers that still import ORM models directly.
# Each entry: (context, module_string)
# TODO: Eliminate each entry as the controller is migrated to use
#       application services / providers exclusively.

_TRANSITIONAL_CONTROLLER_ORM_IMPORTS: set[tuple[str, str]] = {
    # AI / Agents context (transitional — rename from "ai" to "agents")
    ("ai", "infrastructure.persistence.ai.actions.service"),
    ("ai", "infrastructure.persistence.ai.agents.deep.schemas"),
    ("ai", "infrastructure.persistence.ai.agents.models"),
    ("ai", "infrastructure.persistence.ai.agents.service"),
    ("ai", "infrastructure.persistence.ai.conversations.models"),
    ("ai", "infrastructure.persistence.ai.embeddings.factory"),
    ("ai", "infrastructure.persistence.ai.llms.factory"),
    ("ai", "infrastructure.persistence.ai.models"),
    ("ai", "infrastructure.persistence.ai.vector_stores.factory"),
    ("ai", "infrastructure.persistence.project.models"),
    ("ai", "infrastructure.persistence.team.models"),
    ("ai", "infrastructure.persistence.uploads.models"),
    ("ai", "infrastructure.persistence.users.models"),
    ("ai", "infrastructure.persistence.workspaces.models"),
    ("ai", "django.db.models"),
    ("agents", "infrastructure.persistence.ai.actions.service"),
    ("agents", "infrastructure.persistence.ai.agents.deep.schemas"),
    ("agents", "infrastructure.persistence.ai.agents.models"),
    ("agents", "infrastructure.persistence.ai.agents.service"),
    ("agents", "infrastructure.persistence.ai.conversations.models"),
    ("agents", "infrastructure.persistence.ai.embeddings.factory"),
    ("agents", "infrastructure.persistence.ai.llms.factory"),
    ("agents", "infrastructure.persistence.ai.models"),
    ("agents", "infrastructure.persistence.ai.vector_stores.factory"),
    ("agents", "infrastructure.persistence.project.models"),
    ("agents", "infrastructure.persistence.team.models"),
    ("agents", "infrastructure.persistence.uploads.models"),
    ("agents", "infrastructure.persistence.users.models"),
    ("agents", "infrastructure.persistence.workspaces.models"),
    ("agents", "django.db.models"),
    # Budgeting context
    ("budgeting", "infrastructure.persistence.budget.categories.models"),
    ("budgeting", "infrastructure.persistence.budget.models"),
    ("budgeting", "infrastructure.persistence.budget.transactions.models"),
    ("budgeting", "infrastructure.persistence.workspaces.models"),
    ("budgeting", "django.db.models"),
    ("budgeting", "django.db.models.functions"),
    # Project context — controller still uses ORM models directly (transitional)
    ("project", "infrastructure.persistence.project.models"),
    ("project", "infrastructure.persistence.team.models"),
    ("project", "infrastructure.persistence.team.serializers"),
    ("project", "infrastructure.persistence.team.utilities"),
    ("project", "infrastructure.persistence.users.models"),
    ("project", "infrastructure.persistence.users.permissions"),
    ("project", "infrastructure.persistence.workspaces.models"),
    ("project", "infrastructure.persistence.workspaces.utils"),
    ("project", "django.db"),
    ("project", "django.db.models"),
    # Content context — controller still uses ORM models directly (transitional)
    ("content", "infrastructure.persistence.workspaces.news.models"),
    ("content", "django.db.models"),
    # Commerce context — store.models and sponsorship.ledger.services eliminated
    ("commerce", "infrastructure.persistence.marketplace.cart.models"),
    ("commerce", "infrastructure.persistence.marketplace.shop.models"),
    # Identity context
    ("identity", "infrastructure.persistence.budget.models"),
    ("identity", "infrastructure.persistence.notifications.models"),
    ("identity", "infrastructure.persistence.notifications.services"),
    ("identity", "infrastructure.persistence.social.models"),
    ("identity", "infrastructure.persistence.team.models"),
    ("identity", "infrastructure.persistence.team.serializers"),
    ("identity", "infrastructure.persistence.users.models"),
    ("identity", "infrastructure.persistence.users.tasks"),
    ("identity", "infrastructure.persistence.workspaces.models"),
    ("identity", "django.db.models"),
    # Notifications context
    ("notifications", "infrastructure.persistence.notifications.models"),
    ("notifications", "infrastructure.persistence.notifications.userpreferences.models"),
    # Payments context
    ("payments", "infrastructure.persistence.team.models"),
    ("payments", "infrastructure.persistence.users.models"),
    ("payments", "infrastructure.persistence.workspaces.models"),
    ("payments", "infrastructure.persistence.workspaces.payments.models"),
    ("payments", "django.db"),
    ("payments", "django.db.models"),
    # Reports context
    ("reports", "infrastructure.persistence.workspaces.models"),
    # Shared platform
    ("shared_platform", "infrastructure.persistence.broadcast.models"),
    ("shared_platform", "infrastructure.persistence.budget.transactions.models"),
    ("shared_platform", "infrastructure.persistence.core.models"),
    ("shared_platform", "infrastructure.persistence.honeypot.models"),
    ("shared_platform", "infrastructure.persistence.landing.contact.models"),
    ("shared_platform", "infrastructure.persistence.landing.contact.tasks"),
    ("shared_platform", "infrastructure.persistence.landing.models"),
    ("shared_platform", "infrastructure.persistence.marketplace.shop.models"),
    ("shared_platform", "infrastructure.persistence.sponsorship.donations.models"),
    ("shared_platform", "infrastructure.persistence.sponsorship.donations.serializers"),
    ("shared_platform", "infrastructure.persistence.sponsorship.events.models"),
    ("shared_platform", "infrastructure.persistence.sponsorship.events.serializers"),
    ("shared_platform", "infrastructure.persistence.uploads.models"),
    ("shared_platform", "infrastructure.persistence.users.models"),
    ("shared_platform", "infrastructure.persistence.workspaces.news.models"),
    ("shared_platform", "infrastructure.persistence.workspaces.news.serializers"),
    ("shared_platform", "django.db.models"),
    # Sponsorship context
    ("sponsorship", "infrastructure.persistence.ai.services.social"),
    ("sponsorship", "infrastructure.persistence.budget.categories.models"),
    ("sponsorship", "infrastructure.persistence.budget.models"),
    ("sponsorship", "infrastructure.persistence.landing.models"),
    ("sponsorship", "infrastructure.persistence.sponsorship.campaign.models"),
    ("sponsorship", "infrastructure.persistence.sponsorship.communications.models"),
    ("sponsorship", "infrastructure.persistence.sponsorship.donations.models"),
    ("sponsorship", "infrastructure.persistence.sponsorship.events.models"),
    # sponsorship ledger.models: eliminated — now in OrmRecipientLedgerRepository (Phase 9)
    # sponsorship ledger/donations/sponsors/campaign.services: migrated to components.sponsorship.infrastructure
    ("sponsorship", "infrastructure.persistence.sponsorship.recipients.models"),
    ("sponsorship", "infrastructure.persistence.sponsorship.sponsors.models"),
    ("sponsorship", "infrastructure.persistence.workspaces.models"),
    ("sponsorship", "infrastructure.persistence.workspaces.payments.models"),
    ("sponsorship", "django.db.models"),
    # Team context — fully migrated! No transitional ORM imports remaining.
    # Workflow context — controller still uses ORM models directly (transitional)
    ("workflow", "infrastructure.persistence.workspaces.workflows.models"),
    ("workflow", "django.db"),
    # Workspace context
    ("workspace", "infrastructure.persistence.budget.categories.models"),
    ("workspace", "infrastructure.persistence.budget.models"),
    ("workspace", "infrastructure.persistence.budget.transactions.models"),
    ("workspace", "infrastructure.persistence.countries.models"),
    ("workspace", "infrastructure.persistence.notifications.userpreferences.models"),
    ("workspace", "infrastructure.persistence.project.models"),
    ("workspace", "infrastructure.persistence.sectors.models"),
    ("workspace", "infrastructure.persistence.social.models"),
    ("workspace", "infrastructure.persistence.team.models"),
    ("workspace", "infrastructure.persistence.team.serializers"),
    ("workspace", "infrastructure.persistence.users.models"),
    # aggregations_controller.py: eliminated — now delegates through
    # FinancialAggregationsQueryProvider (Phase 9)
    ("workspace", "infrastructure.persistence.workspaces.models"),
    ("workspace", "django.db"),
    ("workspace", "django.db.models"),
}


def _iter_python_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(f for f in path.rglob("*.py") if f.is_file())


def _imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(), filename=str(source_file))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    return imported


def test_controllers_do_not_import_orm_models_directly():
    """Controllers should not import from infrastructure.*.models or django.db.

    All business data access should go through application services,
    providers, or query services — not direct ORM model usage.
    """
    violations: list[str] = []

    for ctx in _CONTEXTS:
        api_dir = COMPONENTS_DIR / ctx / "api"
        for src in _iter_python_files(api_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                is_orm_import = (
                    mod.startswith("infrastructure.persistence.") and ".models" in mod
                ) or (
                    mod.startswith("django.db")
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".service" in mod
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".factory" in mod
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".tasks" in mod
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".schemas" in mod
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".base" in mod
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".serializers" in mod
                ) or (
                    mod.startswith("infrastructure.persistence.") and ".prompts" in mod
                )

                if not is_orm_import:
                    continue

                if (ctx, mod) in _TRANSITIONAL_CONTROLLER_ORM_IMPORTS:
                    continue

                violations.append(
                    f"{src.relative_to(ROOT)} in '{ctx}' imports "
                    f"ORM/legacy module directly: {mod}. "
                    "Use a provider or application service instead."
                )

    assert not violations, (
        "Controllers must not import ORM models or legacy app modules directly:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
