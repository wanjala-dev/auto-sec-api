"""Scaffold a new agent class, tools, and tests."""
from __future__ import annotations

from pathlib import Path
from typing import List

from django.core.management.base import BaseCommand, CommandError

from components.agents.infrastructure.services.agents_service import register_agent_type


class Command(BaseCommand):
    help = "Scaffold a new agent (class + tools + tests)."

    def add_arguments(self, parser):
        parser.add_argument("slug", type=str, help="Agent slug (e.g., legal, security)")
        parser.add_argument("--name", type=str, help="Human-friendly agent name")
        parser.add_argument("--no-tools", action="store_true", help="Skip generating tools module")
        parser.add_argument("--no-tests", action="store_true", help="Skip generating test module")
        parser.add_argument("--create-agent-type", action="store_true", help="Create/refresh AgentType record")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be created without writing files")

    def handle(self, *args, **options):
        slug = options["slug"].strip()
        if not slug:
            raise CommandError("slug is required")
        if slug.endswith("_agent"):
            slug = slug[: -len("_agent")]

        name = options.get("name") or slug.replace("_", " ").title()
        class_name = f"{name.replace(' ', '')}Agent"

        base_dir = Path("apps/ai/agents")
        tool_dir = base_dir / "tools"
        test_dir = base_dir / "tests"

        agent_file = base_dir / f"{slug}_agent.py"
        tool_file = tool_dir / f"{slug}_agent.py"
        test_file = test_dir / f"test_{slug}_agent.py"

        plans: List[tuple[Path, str]] = []

        agent_template = f'''"""{{name}} Agent."""\nfrom functools import partial\nfrom langchain.tools import Tool\n\nfrom .base import BaseAgent\nfrom .tools import {slug}_agent as {slug}_tools\n\n\nclass {class_name}(BaseAgent):\n    """Agent for {name.lower()} workflows."""\n\n    def _setup_tools(self):\n        self.tools = [\n            Tool(\n                name="sample_{slug}_tool",\n                description="Example tool for {name} agent (replace with real tools).",\n                func=partial({slug}_tools.sample_tool, self),\n            ),\n        ]\n'''.format(slug=slug, name=name, class_name=class_name)

        tool_template = f'''"""Tools for {name} agent."""\nfrom __future__ import annotations\n\nfrom typing import Any\n\n\ndef sample_tool(agent, payload: Any) -> str:\n    """Return a placeholder response for scaffolding."""\n    return "TODO: implement {name} tool logic."\n'''.format(name=name)

        test_template = f'''"""Smoke tests for {name} agent."""\nimport pytest\n\n\n@pytest.mark.django_db\ndef test_{slug}_agent_scaffold():\n    assert True\n'''.format(slug=slug, name=name)

        if agent_file.exists():
            raise CommandError(f"Agent file already exists: {agent_file}")
        plans.append((agent_file, agent_template))

        if not options["no_tools"]:
            if tool_file.exists():
                raise CommandError(f"Tool file already exists: {tool_file}")
            plans.append((tool_file, tool_template))

        if not options["no_tests"]:
            if test_file.exists():
                raise CommandError(f"Test file already exists: {test_file}")
            plans.append((test_file, test_template))

        if options["dry_run"]:
            for path, _content in plans:
                self.stdout.write(f"[dry-run] would create {path}")
        else:
            for path, content in plans:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                self.stdout.write(f"Created {path}")

        if options["create_agent_type"]:
            register_agent_type(
                slug=f"{slug}_agent",
                name=f"{name} Agent",
                class_path=f"ai.agents.{slug}_agent.{class_name}",
                description=f"Handles {name.lower()} workflows.",
                aliases=[slug],
            )
            self.stdout.write("AgentType registered/updated.")
