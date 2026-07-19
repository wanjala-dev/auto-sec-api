from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from components.workspace.application.use_cases.bootstrap_workspace_content_use_case import (
    BootstrapWorkspaceContentUseCase,
)


def test_workspace_content_use_case_seeds_workspace_content_and_returns_emission_data():
    workspace_bootstrap_store = Mock()
    workspace_bootstrap_store.seed_projects.return_value = ["Alpha", "Beta"]
    workspace_bootstrap_store.seed_pdfs.return_value = ["missing file"]
    use_case = BootstrapWorkspaceContentUseCase(
        workspace_bootstrap_store=workspace_bootstrap_store,
    )

    result = use_case.execute(
        {
            "contributor": {"email": "helper@example.com"},
            "projects": [{"title": "Alpha"}],
            "recipients": [{"name": "Recipient"}],
            "recipients_category": {"label": "General"},
            "news": [{"title": "Update"}],
            "pdfs": [{"path": "deck.pdf"}],
        },
        config_dir=Path("/tmp/config"),
        workspace=object(),
        owner=object(),
        staff_team=object(),
        contributors_team=object(),
    )

    workspace_bootstrap_store.ensure_contributor_user.assert_called_once()
    workspace_bootstrap_store.seed_projects.assert_called_once()
    workspace_bootstrap_store.seed_recipients.assert_called_once()
    workspace_bootstrap_store.seed_news.assert_called_once()
    workspace_bootstrap_store.seed_pdfs.assert_called_once()
    assert result.project_titles == ["Alpha", "Beta"]
    assert result.pdf_warnings == ["missing file"]
