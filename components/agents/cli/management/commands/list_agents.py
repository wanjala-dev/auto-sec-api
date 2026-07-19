"""
List Available Agents Management Command

Shows all available AI agents and their capabilities.
"""
from django.core.management.base import BaseCommand

from components.agents.infrastructure.adapters.langchain.base import AgentRegistry, BaseAgent
from components.agents.infrastructure.services.agents_service import get_agent_service


class Command(BaseCommand):
    help = 'List all available AI agents and their capabilities'

    def add_arguments(self, parser):
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed information about each agent',
        )

    def handle(self, *args, **options):
        detailed = options.get('detailed', False)

        service = get_agent_service()
        available_agents = service.list_available_agent_types()

        self.stdout.write(
            self.style.SUCCESS(f'🤖 Available AI Agents ({len(available_agents)} total)\n')
        )

        for agent in available_agents:
            slug = agent['slug']
            agent_class = AgentRegistry.get_agent_class(slug)

            if detailed and agent_class:
                self._show_detailed_agent_info(slug, agent_class)
            else:
                self._show_basic_agent_info(agent)

    def _show_basic_agent_info(self, agent_details):
        """Show basic information about an agent"""
        slug = agent_details['slug']
        name = agent_details.get('name', slug.replace('_', ' ').title())
        description = agent_details.get('description') or f'{name} agent'

        self.stdout.write(f"  • {slug}: {name} – {description}")

    def _show_detailed_agent_info(self, agent_type, agent_class):
        """Show detailed information about an agent"""
        self.stdout.write(f'\n📋 {agent_type.upper()} AGENT')
        self.stdout.write('=' * 50)

        # Get agent description from docstring
        docstring = agent_class.__doc__ or 'No description available'
        self.stdout.write(f'Description: {docstring.strip()}')

        # Show capabilities if available
        if hasattr(agent_class, '_setup_tools'):
            # Create a temporary instance to get tools (without actually creating the agent)
            try:
                # This is a bit hacky, but we need to see what tools the agent would have
                temp_agent = agent_class('temp', 'temp', 'temp')
                tools = temp_agent.tools

                self.stdout.write(f'\nTools ({len(tools)}):')
                for tool in tools:
                    self.stdout.write(f'  • {tool.name}: {tool.description}')

            except Exception as e:
                self.stdout.write(f'\nTools: Unable to load tools - {str(e)}')

        self.stdout.write('')
