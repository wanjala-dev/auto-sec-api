"""
Agent Seeding Management Command

Automatically creates and workspaces all available AI agents for workspaces,
making them immediately available for user interaction.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from components.agents.infrastructure.services.agents_service import get_agent_service
from infrastructure.persistence.ai.agents.models import Agent
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.team.models import Team
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = 'Workspace all available AI agents for workspaces. Creates agents for workspace owners and team members.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--workspace-id',
            type=str,
            help='Specific workspace ID to create agents for',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Create agents for ALL workspaces',
        )
        parser.add_argument(
            '--agent-type',
            type=str,
            help='Specific agent type to create (financial_agent, task_agent, etc.)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating agents',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ignore workspace agent entitlements when creating agents',
        )

    def handle(self, *args, **options):
        specific_workspace_id = options.get('workspace_id')
        all_workspaces = options.get('all', False)
        agent_type = options.get('agent_type')
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)

        service = get_agent_service()
        catalogue = service.list_available_agent_types()
        type_lookup = {entry['slug']: entry for entry in catalogue}
        available_agents = list(type_lookup.keys())
        alias_map = {}
        for entry in catalogue:
            for alias in entry.get('aliases') or []:
                alias_map[alias] = entry['slug']

        if agent_type:
            requested = alias_map.get(agent_type, agent_type)
            if requested not in available_agents:
                self.stdout.write(
                    self.style.ERROR(f'Agent type "{agent_type}" not found. Available: {available_agents}')
                )
                return
            available_agents = [requested]

        self.stdout.write('Available agent types:')
        for slug in available_agents:
            details = type_lookup.get(slug, {'name': slug})
            name = details.get('name', slug)
            aliases = details.get('aliases') or []
            alias_str = f" (aliases: {', '.join(aliases)})" if aliases else ''
            self.stdout.write(f"  • {slug} – {name}{alias_str}")

        # Get workspaces to process
        if specific_workspace_id:
            try:
                workspaces = [Workspace.objects.get(id=specific_workspace_id)]
                self.stdout.write(f'Processing specific workspace: {specific_workspace_id}')
            except Workspace.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Workspace with ID {specific_workspace_id} not found')
                )
                return
        else:
            # Get all workspaces
            workspaces = Workspace.objects.all()
            self.stdout.write(f'Processing {workspaces.count()} workspaces')

        total_created = 0
        total_skipped = 0
        processed_workspaces = 0

        for workspace in workspaces:
            self.stdout.write(f'\nProcessing workspace: "{workspace.workspace_name}" (ID: {workspace.id})')

            # Get users who should have access to agents for this workspace
            users_to_create_agents_for = self._get_users_for_workspace(workspace)

            if not users_to_create_agents_for:
                self.stdout.write(
                    self.style.WARNING(f'No users found for workspace "{workspace.workspace_name}" - skipping')
                )
                total_skipped += 1
                continue

            workspace_created_count = 0

            for user in users_to_create_agents_for:
                self.stdout.write(f'  Creating agents for user: {user.get_full_name() or user.username}')

                for agent_type in available_agents:
                    if not force:
                        try:
                            from components.agents.application.policies.agent_entitlements import is_agent_enabled_for_workspace

                            if not is_agent_enabled_for_workspace(str(workspace.id), agent_type):
                                self.stdout.write(
                                    f'    ⚠ Skipped {agent_type} agent (not enabled for workspace)'
                                )
                                continue
                        except Exception:
                            self.stdout.write(
                                f'    ⚠ Skipped {agent_type} agent (entitlement check failed)'
                            )
                            continue
                    if dry_run:
                        self.stdout.write(
                            f'    [DRY RUN] Would create {agent_type} agent for user {user.id}'
                        )
                        workspace_created_count += 1
                    else:
                        try:
                            # Check if agent already exists
                            existing_agent = Agent.objects.filter(
                                user=user,
                                workspace_id=str(workspace.id),
                                agent_type=agent_type
                            ).first()

                            if existing_agent:
                                self.stdout.write(
                                    f'    ⚠ Skipped {agent_type} agent (already exists: {existing_agent.agent_id})'
                                )
                                continue

                            # Create agent using the service
                            service = get_agent_service()
                            agent_info = service.create_agent(
                                agent_type=agent_type,
                                user_id=str(user.id),
                                workspace_id=str(workspace.id),
                                config={
                                    'model_name': 'gpt-3.5-turbo',
                                    'temperature': 0.1
                                }
                            )

                            self.stdout.write(
                                f'    ✓ Created {agent_type} agent (ID: {agent_info["agent_id"]})'
                            )
                            workspace_created_count += 1

                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(f'    ✗ Failed to create {agent_type} agent: {str(e)}')
                            )

            if workspace_created_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'  Created {workspace_created_count} agents for workspace "{workspace.workspace_name}"')
                )
                total_created += workspace_created_count
                processed_workspaces += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'  No agents created for workspace "{workspace.workspace_name}"')
                )
                total_skipped += 1

        # Summary
        self.stdout.write(
                self.style.SUCCESS(
                f'\n🎉 Seeding Complete!\n'
                f'Processed: {processed_workspaces} workspaces\n'
                f'Created: {total_created} agents total\n'
                f'Skipped: {total_skipped} workspaces'
            )
        )

    def _get_users_for_workspace(self, workspace):
        """Get all users who should have access to agents for this workspace"""
        users = set()

        # Add workspace owner
        if workspace.workspace_owner:
            users.add(workspace.workspace_owner)

        # Add team members
        teams = Team.objects.filter(workspace=workspace, status='active')
        for team in teams:
            users.update(team.members.all())

        return list(users)
