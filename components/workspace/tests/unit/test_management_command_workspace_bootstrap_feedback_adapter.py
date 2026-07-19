from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.infrastructure.adapters.management_command_workspace_bootstrap_feedback_adapter import (
    ManagementCommandWorkspaceBootstrapFeedbackAdapter,
)


def test_workspace_feedback_adapter_writes_styled_messages():
    stdout = SimpleNamespace(write=Mock())
    style = SimpleNamespace(
        SUCCESS=lambda message: f"success:{message}",
        NOTICE=lambda message: f"notice:{message}",
        WARNING=lambda message: f"warning:{message}",
    )
    adapter = ManagementCommandWorkspaceBootstrapFeedbackAdapter(
        SimpleNamespace(stdout=stdout, style=style)
    )

    adapter.success("ok")
    adapter.notice("heads-up")
    adapter.warning("careful")

    assert stdout.write.call_args_list[0].args == ("success:ok",)
    assert stdout.write.call_args_list[1].args == ("notice:heads-up",)
    assert stdout.write.call_args_list[2].args == ("warning:careful",)
