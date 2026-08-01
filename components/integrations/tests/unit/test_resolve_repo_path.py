"""Unit tests for monorepo path resolution (``resolve_repo_path``, ADR 0010).

Pure logic — the ``adapter`` is a tiny fake whose only job is ``list_tree``. Covers
the explicit ``repo_root`` override (no tree fetch), the auto-detect suffix-match
(unique, shallowest-wins, ambiguous, none).
"""

from __future__ import annotations

import pytest

from components.integrations.application.log_patch_advisor_service import (
    RepoPathResolutionError,
    resolve_repo_path,
)

_RUNTIME = "components/knowledge/application/providers/ai_embeddings_provider.py"


class _FakeAdapter:
    def __init__(self, tree: list[str]):
        self._tree = tree
        self.list_tree_calls = 0

    def list_tree(self, repo, ref):
        self.list_tree_calls += 1
        return self._tree


@pytest.mark.unit
class TestResolveRepoPath:
    def test_explicit_override_prefixes_without_tree_fetch(self):
        adapter = _FakeAdapter(tree=[])
        resolved = resolve_repo_path(
            adapter=adapter, repo="w/app", ref="main", runtime_path=_RUNTIME, explicit_prefix="api-v2.0"
        )
        assert resolved == f"api-v2.0/{_RUNTIME}"
        assert adapter.list_tree_calls == 0  # override never lists the tree

    def test_explicit_override_strips_slashes(self):
        adapter = _FakeAdapter(tree=[])
        resolved = resolve_repo_path(
            adapter=adapter, repo="w/app", ref="main", runtime_path="/" + _RUNTIME, explicit_prefix="/api-v2.0/"
        )
        assert resolved == f"api-v2.0/{_RUNTIME}"

    def test_auto_detect_unique_suffix_match(self):
        prefixed = f"api-v2.0/{_RUNTIME}"
        adapter = _FakeAdapter(tree=["README.md", prefixed, "docs/x.md"])
        resolved = resolve_repo_path(adapter=adapter, repo="w/app", ref="main", runtime_path=_RUNTIME)
        assert resolved == prefixed
        assert adapter.list_tree_calls == 1

    def test_auto_detect_exact_root_match(self):
        adapter = _FakeAdapter(tree=["README.md", _RUNTIME])
        resolved = resolve_repo_path(adapter=adapter, repo="w/app", ref="main", runtime_path=_RUNTIME)
        assert resolved == _RUNTIME

    def test_auto_detect_shallowest_prefix_wins(self):
        shallow = f"api-v2.0/{_RUNTIME}"
        deep = f"vendored/copy/api-v2.0/{_RUNTIME}"
        adapter = _FakeAdapter(tree=[deep, shallow])
        resolved = resolve_repo_path(adapter=adapter, repo="w/app", ref="main", runtime_path=_RUNTIME)
        assert resolved == shallow

    def test_auto_detect_ambiguous_same_depth_raises(self):
        a = f"backend/{_RUNTIME}"
        b = f"legacy/{_RUNTIME}"
        adapter = _FakeAdapter(tree=[a, b])
        with pytest.raises(RepoPathResolutionError) as exc:
            resolve_repo_path(adapter=adapter, repo="w/app", ref="main", runtime_path=_RUNTIME)
        assert exc.value.reason == "ambiguous_candidate_path"
        assert "repo_root" in str(exc.value)

    def test_auto_detect_no_match_raises_not_in_repo(self):
        adapter = _FakeAdapter(tree=["README.md", "src/other.py"])
        with pytest.raises(RepoPathResolutionError) as exc:
            resolve_repo_path(adapter=adapter, repo="w/app", ref="main", runtime_path=_RUNTIME)
        assert exc.value.reason == "candidate_file_not_in_repo"
