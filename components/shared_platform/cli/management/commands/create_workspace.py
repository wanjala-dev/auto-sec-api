"""Management command to workspace organizations from JSON configuration files.

Supports:
- Single config via --config /absolute/path/to/config.json
- Multiple configs in a directory via --config-dir /absolute/path/to/dir
"""
from __future__ import annotations

from django.core.management import BaseCommand, CommandError, call_command
from components.workspace.application.facades.workspace_bootstrap_facade import (
    WorkspaceBootstrapConfigurationError,
    WorkspaceBootstrapFacade,
)


class Command(BaseCommand):
    help = "Create or update organizations from JSON config(s). Use --config for one file or --config-dir for many."

    def add_arguments(self, parser):
        parser.add_argument('--config', help='Path to JSON config describing one organization')
        parser.add_argument('--config-dir', help='Path to directory containing multiple organization JSON files')
        parser.add_argument('--owner-email', help='Override owner email from config/preset')
        parser.add_argument('--owner-password', help='Override owner password from config/preset')
        parser.add_argument('--skip-defaults', action='store_true', help='Skip running bootstrap_workspace_defaults beforehand')

    def _bootstrap_defaults(self):
        self.stdout.write(self.style.NOTICE("Bootstrapping reference data"))
        call_command("bootstrap_workspace_defaults")

    def handle(self, *args, **options):
        try:
            WorkspaceBootstrapFacade().execute(
                command=self,
                options=options,
                bootstrap_defaults=self._bootstrap_defaults,
            )
        except WorkspaceBootstrapConfigurationError as exc:
            raise CommandError(str(exc)) from exc
