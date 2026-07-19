"""
Show Available Agents for Workspace Management Command

Shows all available AI agents for a specific workspace and user.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from components.agents.infrastructure.services.agents_service import get_agent_service
from infrastructure.persistence.workspaces.models import Workspace
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = 'Show all available AI agents for a specific workspace and user'

    def add_arguments(self, parser):
        parser.add_argument(
            '--workspace-id',
            type=str,
            required=True,
            help='Workspace ID to show agents for',
        )
        parser.add_argument(
            '--user-id',
            type=str,
            help='Specific user ID (defaults to workspace owner)',
        )

    def handle(self, *args, **options):
        workspace_id = options.get('workspace_id')
        user_id = options.get('user_id')

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Workspace with ID {workspace_id} not found')
            )
            return

        # Get user
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User with ID {user_id} not found')
                )
                return
        else:
            user = workspace.workspace_owner
            if not user:
                self.stdout.write(
                    self.style.ERROR(f'No workspace owner found for workspace "{workspace.workspace_name}"')
                )
                return

        self.stdout.write(f'🤖 Available AI Agents for Workspace: "{workspace.workspace_name}"')
        self.stdout.write(f'👤 User: {user.get_full_name() or user.username}')
        self.stdout.write('=' * 60)

        # Get agent service and list active agents
        service = get_agent_service()
        all_active_agents = service.list_user_workspace_agents(str(user.id), str(workspace.id))

        if not all_active_agents:
            self.stdout.write(
                self.style.WARNING('No active agents found for this user and workspace.')
            )
            self.stdout.write('\nTo create agents, run:')
            self.stdout.write(f'  python manage.py workspace_agents --workspace-id {workspace_id}')
            return

        # Group agents by type
        agents_by_type = {}
        for agent in all_active_agents:
            agent_type = agent['agent_type'].lower().replace('agent', '').strip()
            if agent_type not in agents_by_type:
                agents_by_type[agent_type] = []
            agents_by_type[agent_type].append(agent)

        # Display agents
        for agent_type, agents in agents_by_type.items():
            self.stdout.write(f'\n📋 {agent_type.upper()} AGENTS')
            self.stdout.write('-' * 40)

            for agent in agents:
                status_emoji = "🟢" if agent['status'] == "active" else "🔴"
                self.stdout.write(f'  {status_emoji} {agent["agent_id"]}')
                self.stdout.write(f'     Status: {agent["status"]}')
                self.stdout.write(f'     Created: {agent["created_at"]}')
                if agent.get('updated_at'):
                    self.stdout.write(f'     Last Used: {agent["updated_at"]}')
                self.stdout.write('')

        # Show usage examples
        self.stdout.write('\n💡 USAGE EXAMPLES')
        self.stdout.write('-' * 40)
        self.stdout.write('You can interact with these agents through:')
        self.stdout.write('')
        self.stdout.write('1. Natural Language in Workspace Chat:')
        self.stdout.write('   • "Use the financial agent to create an expense of $50"')
        self.stdout.write('   • "Automate task creation for the website redesign project"')
        self.stdout.write('   • "Agent, process this receipt and categorize it"')
        self.stdout.write('')
        self.stdout.write('2. Direct API Calls:')
        for agent_type in agents_by_type.keys():
            agent = agents_by_type[agent_type][0]  # Use first agent as example
            self.stdout.write(f'   • POST /ai/agents/{agent["agent_id"]}/execute/')
        self.stdout.write('')
        self.stdout.write('3. Frontend Integration:')
        self.stdout.write('   • See FRONTEND_INTEGRATION.md for detailed examples')
