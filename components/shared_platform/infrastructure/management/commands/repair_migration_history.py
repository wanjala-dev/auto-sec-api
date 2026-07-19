"""
Repair inconsistent migration history between legacy `children` shim migrations
and the canonical `recipients` app.

This addresses cases where databases have `children.*` migrations recorded as
applied, but the corresponding `recipients.*` migrations were never recorded,
causing `python manage.py migrate` to abort with InconsistentMigrationHistory.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.migrations.recorder import MigrationRecorder


@dataclass(frozen=True)
class RepairPlan:
    db_alias: str
    children_to_unapply: tuple[str, ...]
    children_to_apply: tuple[str, ...]


def _migration_names_in(package_path: Path) -> set[str]:
    return {
        path.stem
        for path in package_path.glob("[0-9][0-9][0-9][0-9]_*.py")
        if path.is_file()
    }

def _resolve_migrations_path(import_paths: tuple[str, ...]) -> Path | None:
    """
    Resolve a migrations package path from a list of import paths.

    This command runs during startup in some environments; if the legacy shim app
    has been removed (e.g., `children`), we treat it as absent and proceed with
    an empty migration set rather than crashing the process.
    """
    for import_path in import_paths:
        try:
            module = import_module(import_path)
        except ModuleNotFoundError:
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        return Path(module_file).parent
    return None


def build_repair_plan(
    *,
    db_alias: str,
    applied: set[tuple[str, str]],
    children_migrations_path: Path | None = None,
    recipients_migrations_path: Path | None = None,
) -> RepairPlan:
    """
    Identify legacy `recipients` migrations to unapply so history becomes consistent.

    Strategy: unapply (delete from django_migrations) any `recipients` migration
    that is applied while the same-named `recipients` migration is not.
    Also mark missing `recipients` migrations as applied if they have no operations
    and are required by other applied migrations.
    """
    if children_migrations_path is None:
        children_migrations_path = _resolve_migrations_path(
            (
                "infrastructure.children.migrations",
                "infrastructure.sponsorship.children.migrations",
            )
        ) or (Path(__file__).resolve().parent / "_missing_children_migrations")
    if recipients_migrations_path is None:
        recipients_migrations_path = _resolve_migrations_path(
            (
                "infrastructure.sponsorship.recipients.migrations",
                "infrastructure.recipients.migrations",
            )
        ) or (Path(__file__).resolve().parent / "_missing_recipients_migrations")

    children_migration_names = _migration_names_in(children_migrations_path)
    recipient_migration_names = _migration_names_in(recipients_migrations_path)
    shim_names = children_migration_names & recipient_migration_names

    # Don't unapply migrations that are dependencies of other applied migrations
    # First, identify which recipients migrations are needed as dependencies
    needed_children_migrations = set()
    if ("budget", "0005_initial") in applied:
        needed_children_migrations.add("0002_goal_seed")
    if ("sponsors", "0001_initial") in applied:
        needed_children_migrations.add("0001_initial")
    if ("donations", "0005_donation_child_fk") in applied:
        needed_children_migrations.add("0003_initial")
        # 0003_initial depends on 0002_goal_seed
        needed_children_migrations.add("0002_goal_seed")
    if ("budget", "0007_auto_20251019_0353") in applied:
        needed_children_migrations.add("0004_alter_tag_id")
    if ("workspaces", "0009_payment_plans") in applied:
        needed_children_migrations.add("0011_child_hidden")
    if ("ledger", "0001_initial") in applied:
        needed_children_migrations.add("0012_auto_20251114_2217")
    
    children_to_unapply = sorted(
        name
        for name in shim_names
        if ("children", name) in applied
        and ("recipients", name) not in applied
        and name not in needed_children_migrations  # Don't unapply if it's needed as a dependency
    )
    
    # Check for missing recipients migrations that are dependencies of applied migrations
    # Scan all applied migrations to find dependencies on recipients migrations
    children_to_apply = set()
    
    # Import migration loader to check dependencies
    from django.db.migrations.loader import MigrationLoader
    from django.db import connections as django_connections
    
    try:
        loader = MigrationLoader(django_connections[db_alias])
        
        # Find all applied migrations that depend on recipients migrations
        for app_label, migration_name in applied:
            try:
                migration_key = (app_label, migration_name)
                if migration_key in loader.disk_migrations:
                    migration = loader.disk_migrations[migration_key]
                    # Check dependencies
                    for dep_app, dep_name in migration.dependencies:
                        if dep_app == "recipients" and (dep_app, dep_name) not in applied:
                            # This recipients migration is missing but needed
                            children_to_apply.add(dep_name)
            except (KeyError, AttributeError):
                # Migration not found in loader, skip
                pass
        
        # Also check transitive dependencies - if we're applying a recipients migration,
        # check if its dependencies are also missing
        children_to_apply_list = list(children_to_apply)
        for children_name in children_to_apply_list:
            try:
                migration_key = ("recipients", children_name)
                if migration_key in loader.disk_migrations:
                    migration = loader.disk_migrations[migration_key]
                    # Check if this migration depends on other recipients migrations
                    for dep_app, dep_name in migration.dependencies:
                        if dep_app == "recipients" and (dep_app, dep_name) not in applied:
                            # Add transitive dependency
                            children_to_apply.add(dep_name)
            except (KeyError, AttributeError):
                pass
    except Exception:
        # Fallback to explicit cases if loader fails
        if ("recipients", "0002_goal_seed") not in applied and ("budget", "0005_initial") in applied:
            children_to_apply.add("0002_goal_seed")
        if ("recipients", "0001_initial") not in applied and ("sponsors", "0001_initial") in applied:
            children_to_apply.add("0001_initial")
        if ("recipients", "0003_initial") not in applied and ("donations", "0005_donation_child_fk") in applied:
            children_to_apply.add("0003_initial")
        if ("recipients", "0004_alter_tag_id") not in applied and ("budget", "0007_auto_20251019_0353") in applied:
            children_to_apply.add("0004_alter_tag_id")
    
    children_to_apply = list(children_to_apply)
    
    # Verify these are safe to apply (have no operations or only proxy models)
    verified_to_apply = []
    for name in children_to_apply:
        migration_file = children_migrations_path / f"{name}.py"
        if migration_file.exists():
            try:
                with open(migration_file, 'r') as f:
                    content = f.read()
                    # Check if operations list is empty (safe to mark as applied)
                    is_empty = 'operations = []' in content
                    # Check if all operations are proxy model creations (also safe)
                    is_proxy_only = (
                        'proxy = True' in content and
                        'CreateModel' in content and
                        'recipients.' in content  # All recipients proxy models base on recipients
                    )
                    if is_empty or is_proxy_only:
                        verified_to_apply.append(name)
            except Exception:
                pass
    
    children_to_apply = verified_to_apply
    
    return RepairPlan(
        db_alias=db_alias,
        children_to_unapply=tuple(children_to_unapply),
        children_to_apply=tuple(children_to_apply)
    )


def format_plan(plan: RepairPlan) -> str:
    if not plan.children_to_unapply and not plan.children_to_apply:
        return "No inconsistencies detected."
    lines = []
    if plan.children_to_unapply:
        lines.extend([
            "Will unapply the following legacy children migrations (history only):",
            *[f"- children.{name}" for name in plan.children_to_unapply],
        ])
    if plan.children_to_apply:
        lines.extend([
            "Will mark the following missing recipients migrations as applied (safe, no operations):",
            *[f"- recipients.{name}" for name in plan.children_to_apply],
        ])
    return "\n".join(lines)


def apply_plan(plan: RepairPlan) -> tuple[int, int]:
    """
    Apply a repair plan by deleting/applying migration rows for the legacy `children` shim app.

    Returns a tuple of (deleted_count, applied_count).
    """
    connection = connections[plan.db_alias]
    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()

    deleted = 0
    applied = 0

    Migration = recorder.Migration
    with transaction.atomic(using=plan.db_alias):
        if plan.children_to_unapply:
            qs = Migration.objects.using(plan.db_alias).filter(
                app="children",
                name__in=plan.children_to_unapply,
            )
            deleted, _ = qs.delete()
        
        if plan.children_to_apply:
            from django.utils import timezone
            from datetime import timedelta
            
            # Calculate timestamps for all migrations first, then apply in dependency order
            # Sort migrations by dependency order (0001 before 0002)
            sorted_to_apply = sorted(plan.children_to_apply)
            timestamps = {}
            
            # First pass: calculate timestamps
            for name in sorted_to_apply:
                migration_timestamp = None
                
                if name == '0002_goal_seed':
                    # budget.0005_initial depends on recipients.0002_goal_seed
                    budget_migration = Migration.objects.using(plan.db_alias).filter(
                        app="budget",
                        name="0005_initial"
                    ).first()
                    if budget_migration:
                        # Set timestamp to be 2 seconds before the dependent migration
                        # (leaving room for recipients.0001_initial if needed)
                        migration_timestamp = budget_migration.applied - timedelta(seconds=2)
                elif name == '0003_initial':
                    # donations.0005_donation_child_fk depends on recipients.0003_initial
                    donations_migration = Migration.objects.using(plan.db_alias).filter(
                        app="donations",
                        name="0005_donation_child_fk"
                    ).first()
                    if donations_migration:
                        # Set timestamp to be 2 seconds before the dependent migration
                        # (leaving room for recipients.0002_goal_seed if needed)
                        migration_timestamp = donations_migration.applied - timedelta(seconds=2)
                    # Also check if recipients.0002_goal_seed is being applied (it depends on it)
                    if "0002_goal_seed" in plan.children_to_apply:
                        # Calculate what timestamp 0002_goal_seed will have
                        goal_seed_timestamp = timestamps.get("0002_goal_seed")
                        if goal_seed_timestamp:
                            # 0003_initial should be 1 second after 0002_goal_seed
                            if migration_timestamp is None or goal_seed_timestamp + timedelta(seconds=1) < migration_timestamp:
                                migration_timestamp = goal_seed_timestamp + timedelta(seconds=1)
                elif name == '0004_alter_tag_id':
                    # budget.0007_auto_20251019_0353 depends on recipients.0004_alter_tag_id
                    budget_0007 = Migration.objects.using(plan.db_alias).filter(
                        app="budget",
                        name="0007_auto_20251019_0353"
                    ).first()
                    if budget_0007:
                        # Set timestamp to be 2 seconds before the dependent migration
                        # (leaving room for recipients.0003_initial if needed)
                        migration_timestamp = budget_0007.applied - timedelta(seconds=2)
                    # Also check if recipients.0003_initial is being applied (it depends on it)
                    if "0003_initial" in plan.children_to_apply:
                        # Calculate what timestamp 0003_initial will have
                        initial_0003_timestamp = timestamps.get("0003_initial")
                        if initial_0003_timestamp:
                            # 0004_alter_tag_id should be 1 second after 0003_initial
                            if migration_timestamp is None or initial_0003_timestamp + timedelta(seconds=1) < migration_timestamp:
                                migration_timestamp = initial_0003_timestamp + timedelta(seconds=1)
                elif name == '0001_initial':
                    # Check if recipients.0002_goal_seed is being applied (it depends on 0001_initial)
                    if "0002_goal_seed" in plan.children_to_apply:
                        # Calculate what timestamp 0002_goal_seed will have
                        budget_migration = Migration.objects.using(plan.db_alias).filter(
                            app="budget",
                            name="0005_initial"
                        ).first()
                        if budget_migration:
                            # 0001_initial should be 1 second before 0002_goal_seed
                            goal_seed_timestamp = budget_migration.applied - timedelta(seconds=2)
                            migration_timestamp = goal_seed_timestamp - timedelta(seconds=1)
                    # Also check sponsors.0001_initial
                    sponsors_migration = Migration.objects.using(plan.db_alias).filter(
                        app="sponsors",
                        name="0001_initial"
                    ).first()
                    if sponsors_migration:
                        # Use the earlier of the two timestamps
                        sponsor_timestamp = sponsors_migration.applied - timedelta(seconds=1)
                        if migration_timestamp is None or sponsor_timestamp < migration_timestamp:
                            migration_timestamp = sponsor_timestamp
                
                # If no dependent migration found, use a very early timestamp
                if migration_timestamp is None:
                    migration_timestamp = timezone.now() - timedelta(days=365)
                
                timestamps[name] = migration_timestamp
            
            # Second pass: apply migrations with calculated timestamps
            for name in sorted_to_apply:
                migration_timestamp = timestamps[name]
                
                # Mark migration as applied with appropriate timestamp
                # Use update_or_create to handle both new and existing records
                migration_obj, created = Migration.objects.using(plan.db_alias).update_or_create(
                    app="recipients",
                    name=name,
                    defaults={"applied": migration_timestamp}
                )
                if created or migration_obj.applied != migration_timestamp:
                    applied += 1
    
    return deleted, applied


class Command(BaseCommand):
    help = (
        "Repair inconsistent migration history between `children` and `recipients` "
        "by unapplying legacy `children.*` shim migrations whose `recipients.*` "
        "counterparts are missing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help="Database alias to use (default: default).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show actions without writing changes.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Apply the changes without prompting.",
        )

    def handle(self, *args, **options):
        db_alias: str = options["database"]
        dry_run: bool = options["dry_run"]
        auto_confirm: bool = options["yes"]

        connection = connections[db_alias]
        recorder = MigrationRecorder(connection)
        recorder.ensure_schema()
        applied = set(recorder.applied_migrations())

        plan = build_repair_plan(db_alias=db_alias, applied=applied)
        self.stdout.write(format_plan(plan))

        if not plan.children_to_unapply and not plan.children_to_apply:
            return

        if dry_run:
            return

        if not auto_confirm:
            raise CommandError("Refusing to modify django_migrations without --yes (or use --dry-run).")

        deleted, applied = apply_plan(plan)
        if deleted > 0:
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} row(s) from django_migrations."))
        if applied > 0:
            self.stdout.write(self.style.SUCCESS(f"Marked {applied} migration(s) as applied in django_migrations."))
        self.stdout.write(f"Next: python manage.py migrate --database={db_alias}")
