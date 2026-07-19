"""Unit tests for the Wave-3 file-backed prompt registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from components.agents.infrastructure.prompts import registry as reg_module
from components.agents.infrastructure.prompts.registry import (
    PromptNotFoundError,
    PromptRegistry,
    PromptRegistryError,
    PromptVersionNotFoundError,
)


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    """Tests freely monkeypatch ``_DATA_DIR`` — bust the per-process cache."""
    PromptRegistry.clear_cache()
    yield
    PromptRegistry.clear_cache()


@pytest.fixture
def fake_data_dir(tmp_path, monkeypatch):
    """Point the registry at a temp directory holding test fixtures."""
    monkeypatch.setattr(reg_module, "_DATA_DIR", tmp_path)
    PromptRegistry.clear_cache()
    return tmp_path


def _write(path: Path, body: str) -> None:
    path.write_text(body)


class TestPromptRegistryGet:
    def test_returns_active_template_by_default(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.prompt.yaml",
            """
id: demo.prompt
description: test
template_variables: []
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: first
    template: |
      hello world
""",
        )
        assert "hello world" in PromptRegistry.get("demo.prompt")

    def test_returns_specific_version(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.prompt.yaml",
            """
id: demo.prompt
description: test
template_variables: []
active: v2
versions:
  v1:
    created_at: 2026-05-01
    created_by: test
    notes: old
    template: |
      old template
  v2:
    created_at: 2026-06-01
    created_by: test
    notes: new
    template: |
      new template
""",
        )
        assert "old template" in PromptRegistry.get("demo.prompt", version="v1")
        assert "new template" in PromptRegistry.get("demo.prompt", version="v2")
        # active resolves to v2.
        assert "new template" in PromptRegistry.get("demo.prompt")

    def test_missing_prompt_id_raises_prompt_not_found(self, fake_data_dir):
        with pytest.raises(PromptNotFoundError) as exc:
            PromptRegistry.get("does.not.exist")
        assert "does.not.exist" in str(exc.value)

    def test_missing_version_raises(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.prompt.yaml",
            """
id: demo.prompt
description: test
template_variables: []
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: ok
    template: |
      hi
""",
        )
        with pytest.raises(PromptVersionNotFoundError):
            PromptRegistry.get("demo.prompt", version="v9")


class TestPromptRegistryRender:
    def test_renders_with_variables(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.greeter.yaml",
            """
id: demo.greeter
description: test
template_variables:
  - name
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: greets
    template: |
      Hello {name}.
""",
        )
        out = PromptRegistry.render("demo.greeter", name="Henry")
        assert "Hello Henry." in out

    def test_render_on_static_prompt_raises(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.static.yaml",
            """
id: demo.static
description: test
template_variables: []
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: ok
    template: |
      static body
""",
        )
        with pytest.raises(PromptRegistryError) as exc:
            PromptRegistry.render("demo.static")
        assert "static" in str(exc.value)

    def test_render_missing_variable_raises(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.needs_var.yaml",
            """
id: demo.needs_var
description: test
template_variables:
  - name
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: ok
    template: |
      Hi {name}.
""",
        )
        with pytest.raises(PromptRegistryError) as exc:
            PromptRegistry.render("demo.needs_var")
        assert "missing=['name']" in str(exc.value)


class TestPromptRegistryValidation:
    def test_id_must_match_filename(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.prompt.yaml",
            """
id: wrong.id
description: test
template_variables: []
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: ok
    template: |
      x
""",
        )
        with pytest.raises(PromptRegistryError) as exc:
            PromptRegistry.get("demo.prompt")
        assert "does not match filename" in str(exc.value)

    def test_active_must_be_in_versions(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.prompt.yaml",
            """
id: demo.prompt
description: test
template_variables: []
active: v9
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: ok
    template: |
      x
""",
        )
        with pytest.raises(PromptRegistryError) as exc:
            PromptRegistry.get("demo.prompt")
        assert "active=" in str(exc.value)

    def test_template_variable_mismatch_caught_at_load(self, fake_data_dir):
        _write(
            fake_data_dir / "demo.prompt.yaml",
            """
id: demo.prompt
description: test
template_variables:
  - name
active: v1
versions:
  v1:
    created_at: 2026-06-07
    created_by: test
    notes: typo
    template: |
      Hi {nme}.
""",
        )
        with pytest.raises(PromptRegistryError) as exc:
            PromptRegistry.get("demo.prompt")
        msg = str(exc.value)
        assert "missing_in_template=['name']" in msg
        assert "undeclared=['nme']" in msg


class TestProductionPromptsLoadCleanly:
    """The five real prompts must validate against the production registry."""

    def test_all_prompts_discoverable(self):
        ids = PromptRegistry.all_prompt_ids()
        assert {
            "estimator.repair",
            "estimator.system",
            "planner.project",
            "planner.system",
            "planner.task",
        }.issubset(set(ids))

    def test_planner_system_renders_with_agent_catalog(self):
        # The only prompt with a template variable today.
        rendered = PromptRegistry.render(
            "planner.system", agent_catalog="- demo: test"
        )
        assert "- demo: test" in rendered

    def test_planner_system_has_v1_and_v2(self):
        # Pinned by the Wave 3 plan: the v1→v2 comparison must exist
        # so the registry isn't YAGNI dead weight.
        versions = PromptRegistry.versions("planner.system")
        assert {"v1", "v2"}.issubset(set(versions))

    def test_static_prompts_get_works(self):
        for pid in ("estimator.repair", "estimator.system",
                    "planner.project", "planner.task"):
            text = PromptRegistry.get(pid)
            assert text.strip(), f"{pid} returned an empty template"
