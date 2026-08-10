"""Unit tests: reading a PR's patch back from GitHub (the legacy-backfill read).

``requests.request`` is stubbed so no real call fires. The load-bearing assertion
is SHAPE EQUIVALENCE: a diff recovered from the host must look like one the open
step computes locally with ``difflib.unified_diff``, or the HUD would render a
backfilled record differently from a freshly-opened one.
"""

from __future__ import annotations

import difflib
import json
from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.application.ports.vcs_port import VcsApiError
from components.integrations.infrastructure.adapters.vcs.github_vcs_adapter import GitHubVcsAdapter

_REQUESTS_PATH = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.requests.request"
_PATH = "components/identity/infrastructure/adapters/apple_auth.py"


def _resp(status_code: int, payload):
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload), json=lambda: payload)


@pytest.mark.unit
class TestGitHubPullRequestPatch:
    def test_prepends_file_headers_to_githubs_hunks(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        files = [{"filename": _PATH, "patch": "@@ -37,7 +37,7 @@\n-    unsafe\n+    safe"}]

        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, files)):
            patch = adapter.get_pull_request_patch("wanjala-dev/api-v0.2.0", 867)

        assert patch.path == _PATH
        assert patch.file_count == 1
        assert patch.diff.startswith(f"--- a/{_PATH}\n+++ b/{_PATH}\n@@ ")
        assert "+    safe" in patch.diff

    def test_shape_matches_a_locally_computed_unified_diff(self):
        """The recovered diff's header lines are byte-identical to difflib's."""
        local = "".join(difflib.unified_diff(["old\n"], ["new\n"], fromfile=f"a/{_PATH}", tofile=f"b/{_PATH}"))
        local_headers = local.splitlines()[:2]

        adapter = GitHubVcsAdapter("ghp_secret_token")
        files = [{"filename": _PATH, "patch": "@@ -1 +1 @@\n-old\n+new"}]
        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, files)):
            patch = adapter.get_pull_request_patch("wanjala-dev/api-v0.2.0", 867)

        assert patch.diff.splitlines()[:2] == local_headers

    def test_concatenates_a_multi_file_pr_and_reports_the_count(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        files = [
            {"filename": "a.py", "patch": "@@ -1 +1 @@\n-a\n+A"},
            {"filename": "b.py", "patch": "@@ -1 +1 @@\n-b\n+B"},
        ]

        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, files)):
            patch = adapter.get_pull_request_patch("acme/app", 12)

        assert patch.path == "a.py"  # primary = first changed file
        assert patch.file_count == 2
        assert "--- a/a.py" in patch.diff
        assert "--- a/b.py" in patch.diff

    def test_a_binary_only_pr_yields_no_diff_rather_than_a_placeholder(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        files = [{"filename": "logo.png", "status": "modified"}]  # GitHub omits `patch`

        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, files)):
            patch = adapter.get_pull_request_patch("acme/app", 12)

        assert patch.diff == ""
        assert patch.file_count == 1

    def test_a_missing_pr_raises_rather_than_returning_an_empty_patch(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")

        with mock.patch(_REQUESTS_PATH, return_value=_resp(404, {"message": "Not Found"})):
            with pytest.raises(VcsApiError) as exc:
                adapter.get_pull_request_patch("acme/app", 999)

        assert exc.value.status_code == 404
        assert "ghp_secret_token" not in str(exc.value)
