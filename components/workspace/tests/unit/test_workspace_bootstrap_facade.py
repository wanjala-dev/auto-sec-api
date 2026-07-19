from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from components.workspace.application.facades.workspace_bootstrap_facade import WorkspaceBootstrapFacade


class _FakeStdout:
    def __init__(self):
        self.messages = []

    def write(self, message):
        self.messages.append(message)


class _FakeStyle:
    @staticmethod
    def NOTICE(message):
        return message


def test_workspace_bootstrap_facade_bootstraps_defaults_and_processes_each_config():
    processed = []

    class _FakeUseCase:
        def execute(self, config, *, owner_email_override=None, owner_password_override=None):
            processed.append((config["workspace"]["name"], owner_email_override, owner_password_override))
            return config["workspace"]["name"]

    class _FakeProvider:
        def build_use_case(self, *, command):
            return _FakeUseCase()

    command = SimpleNamespace(
        stdout=_FakeStdout(),
        style=_FakeStyle(),
    )

    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        alpha_dir = root / "alpha"
        beta_dir = root / "beta"
        alpha_dir.mkdir()
        beta_dir.mkdir()
        (alpha_dir / "config.json").write_text(
            json.dumps({"workspace": {"name": "Alpha"}, "owner": {"email": "alpha@example.com"}}),
            encoding="utf-8",
        )
        (beta_dir / "config.json").write_text(
            json.dumps({"workspace": {"name": "Beta"}, "owner": {"email": "beta@example.com"}}),
            encoding="utf-8",
        )

        # The facade no longer imports Django's call_command directly. The
        # framework-specific "bootstrap defaults" step is injected as a callable
        # (bootstrap_defaults) so the application-layer facade stays free of
        # infrastructure imports. The provider is imported into the facade
        # module, so patch it there by its canonical path.
        bootstrap_defaults = MagicMock()
        with patch(
            "components.workspace.application.facades.workspace_bootstrap_facade"
            ".WorkspaceBootstrapProvider",
            return_value=_FakeProvider(),
        ):
            results = WorkspaceBootstrapFacade().execute(
                command=command,
                options={
                    "config_dir": str(root),
                    "skip_defaults": False,
                    "owner_email": "override@example.com",
                    "owner_password": "secret",
                },
                bootstrap_defaults=bootstrap_defaults,
            )

    bootstrap_defaults.assert_called_once_with()
    assert results == ["Alpha", "Beta"]
    assert processed == [
        ("Alpha", "override@example.com", "secret"),
        ("Beta", "override@example.com", "secret"),
    ]
