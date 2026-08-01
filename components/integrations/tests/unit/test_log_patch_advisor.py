"""Unit tests — patch-path derivation + patch groundedness (no DB, no LLM).

The LLM boundary is a scripted fake port (``chat`` returns a canned
response object); groundedness and path derivation are deterministic.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from components.integrations.application.log_patch_advisor_service import (
    LogPatchAdvisor,
    PatchValidationError,
    derive_candidate_path,
    validate_patch,
)


class _FakeLlm:
    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return SimpleNamespace(content=self._content)


def _payload(message: str, evidence_detail: str = "", suggested_fix: str = "") -> dict:
    return {
        "service": "celery_worker",
        "level": "ERROR",
        "message": message,
        "signal": "ERROR in celery_worker",
        "evidence": [{"type": "log_line", "detail": evidence_detail or message}],
        "suggested_fix": suggested_fix,
    }


@pytest.mark.unit
class TestDeriveCandidatePath:
    def test_traceback_file_frame_wins(self):
        payload = _payload(
            "boom",
            evidence_detail=(
                "Traceback (most recent call last):\n"
                '  File "/app/manage.py", line 10, in main\n'
                '  File "/app/components/workflow/application/service.py", line 42, in run\n'
                "ImportError: cannot import name 'run_due_schedules'"
            ),
        )
        # Deepest (last) frame wins — that's where the error raised.
        assert derive_candidate_path(payload) == "components/workflow/application/service.py"

    def test_traceback_without_app_prefix(self):
        payload = _payload("x", evidence_detail='File "components/agents/base.py", line 3')
        assert derive_candidate_path(payload) == "components/agents/base.py"

    def test_dotted_module_fallback(self):
        payload = _payload(
            "cannot import name 'refresh_recommendable_items' from components.knowledge.application.embedding_service"
        )
        assert derive_candidate_path(payload) == "components/knowledge/application/embedding_service.py"

    def test_longest_dotted_module_wins(self):
        payload = _payload("module workflow.tasks failed importing components.workflow.infrastructure.tasks.runner")
        assert derive_candidate_path(payload) == "components/workflow/infrastructure/tasks/runner.py"

    def test_hostnames_are_not_modules(self):
        payload = _payload("connection to sqs.us-east-1.amazonaws.com timed out")
        assert derive_candidate_path(payload) is None

    def test_no_file_evidence_returns_none(self):
        payload = _payload("something went wrong")
        assert derive_candidate_path(payload) is None


_OLD_CONTENT = "def run_due_schedules():\n    return schedule()\n\n\ndef other():\n    return 1\n"


def _llm_json(updated: str, path: str = "components/workflow/tasks.py", summary: str = "fix") -> str:
    return json.dumps({"path": path, "updated_content": updated, "change_summary": summary})


@pytest.mark.unit
class TestPatchGroundedness:
    def _propose(self, llm_content: str, payload: dict | None = None, old: str = _OLD_CONTENT):
        advisor = LogPatchAdvisor(llm_port=_FakeLlm(llm_content))
        payload = payload or _payload(
            "NameError: name 'schedule' is not defined in run_due_schedules",
            suggested_fix="Import schedule in the module.",
        )
        return advisor.propose(payload=payload, path="components/workflow/tasks.py", current_content=old)

    def test_grounded_patch_touching_salient_token_line_is_accepted(self):
        # Missing-export fix: the ADDED lines carry the finding's salient
        # token (run_due_schedules_hourly) — grounded.
        payload = _payload(
            "ImportError: cannot import name 'run_due_schedules_hourly' from workflow tasks",
            suggested_fix="Add run_due_schedules_hourly to the module.",
        )
        updated = _OLD_CONTENT + "\n\ndef run_due_schedules_hourly():\n    return run_due_schedules()\n"
        proposal = self._propose(_llm_json(updated), payload=payload)
        assert proposal is not None
        assert proposal.path == "components/workflow/tasks.py"
        assert "def run_due_schedules_hourly" in proposal.updated_content

    def test_patch_touching_only_unrelated_lines_is_rejected(self):
        updated = _OLD_CONTENT.replace("def other():\n    return 1", "def other():\n    return 2")
        assert self._propose(_llm_json(updated)) is None

    def test_identical_content_is_rejected(self):
        assert self._propose(_llm_json(_OLD_CONTENT)) is None

    def test_unparseable_output_is_rejected(self):
        assert self._propose("I think you should probably fix the import.") is None

    def test_empty_updated_content_is_rejected(self):
        assert self._propose(_llm_json("")) is None

    def test_evidence_with_no_salient_tokens_is_rejected(self):
        payload = {
            "service": "web",
            "level": "ERROR",
            "message": "it broke",
            "signal": "",
            "evidence": [],
            "suggested_fix": "",
        }
        updated = _OLD_CONTENT + "# fixed\n"
        assert self._propose(_llm_json(updated), payload=payload) is None

    def test_oversized_file_degrades_to_none(self):
        advisor = LogPatchAdvisor(llm_port=_FakeLlm(_llm_json(_OLD_CONTENT + "# x\n")))
        payload = _payload("NameError: run_due_schedules")
        big = "x = 1\n" * 30_000
        assert advisor.propose(payload=payload, path="a.py", current_content=big) is None

    def test_code_fenced_json_is_salvaged(self):
        payload = _payload(
            "ImportError: cannot import name 'run_due_schedules_hourly'",
            suggested_fix="Add run_due_schedules_hourly.",
        )
        updated = _OLD_CONTENT + "\n\ndef run_due_schedules_hourly():\n    return None\n"
        fenced = f"```json\n{_llm_json(updated)}\n```"
        assert self._propose(fenced, payload=payload) is not None

    def test_llm_failure_degrades_to_none(self):
        class _Boom:
            def chat(self, messages):
                raise RuntimeError("llm down")

        advisor = LogPatchAdvisor(llm_port=_Boom())
        payload = _payload("NameError: run_due_schedules")
        assert advisor.propose(payload=payload, path="a.py", current_content=_OLD_CONTENT) is None


# The real #828 module (paraphrased): a ~50-line module whose class the advisor
# deleted, replacing the whole file with a single self-referential import.
_EMBEDDINGS_MODULE = (
    '"""AI embeddings provider — resolves an embeddings port from the registry."""\n'
    "from __future__ import annotations\n"
    "\n"
    "_REGISTRY: dict[str, object] = {}\n"
    "\n"
    "\n"
    "class AIEmbeddingsProvider:\n"
    '    """Factory that returns the configured embeddings adapter."""\n'
    "\n"
    "    def __init__(self, default: str = 'openai') -> None:\n"
    "        self._default = default\n"
    "\n"
    "    def get_port(self, name: str | None = None):\n"
    "        key = name or self._default\n"
    "        adapter = _REGISTRY.get(key)\n"
    "        if adapter is None:\n"
    "            raise KeyError(f'no embeddings adapter registered for {key}')\n"
    "        return adapter\n"
    "\n"
    "    def register(self, name: str, adapter: object) -> None:\n"
    "        _REGISTRY[name] = adapter\n"
    "\n"
    "    @property\n"
    "    def default(self) -> str:\n"
    "        return self._default\n"
)
_EMBEDDINGS_PATH = "components/knowledge/application/providers/ai_embeddings_provider.py"


@pytest.mark.unit
class TestValidatePatch:
    def test_828_destructive_self_import_is_rejected(self):
        # The exact #828 shape: the whole module replaced by a self-referential
        # import that DROPS class AIEmbeddingsProvider.
        gutted = "from components.knowledge.application.providers.ai_embeddings_provider import AIEmbeddingsProvider\n"
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(original_content=_EMBEDDINGS_MODULE, updated_content=gutted, path=_EMBEDDINGS_PATH)
        assert exc.value.reason == "patch_removes_definitions"

    def test_syntax_broken_patch_is_rejected(self):
        broken = _EMBEDDINGS_MODULE + "\n\ndef f(:\n    pass\n"
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(original_content=_EMBEDDINGS_MODULE, updated_content=broken, path=_EMBEDDINGS_PATH)
        assert exc.value.reason == "patch_does_not_parse"

    def test_whole_file_gutted_to_one_unrelated_line(self):
        # A 50-line module reduced to a single UNRELATED line: symbols are dropped,
        # so this is caught (removes_definitions fires before the size check).
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(
                original_content=_EMBEDDINGS_MODULE,
                updated_content="x = 1\n",
                path=_EMBEDDINGS_PATH,
            )
        assert exc.value.reason in ("patch_removes_definitions", "patch_too_destructive")

    def test_size_check_fires_for_non_py_gutting(self):
        # A non-.py config file gutted to a fraction of its size → the size check
        # (the only structural guard for non-.py) rejects it.
        original = "\n".join(f"line {i} = value{i}" for i in range(20)) + "\n"
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(original_content=original, updated_content="line 0 = value0\n", path="config/app.yaml")
        assert exc.value.reason == "patch_too_destructive"

    def test_valid_minimal_alias_fix_passes(self):
        # The CORRECT #828 fix: preserve the class, append a casing alias.
        fixed = _EMBEDDINGS_MODULE + "\n\nAiEmbeddingsProvider = AIEmbeddingsProvider\n"
        # Preserves the original class → alias adds a name, drops none. No raise.
        assert validate_patch(original_content=_EMBEDDINGS_MODULE, updated_content=fixed, path=_EMBEDDINGS_PATH) is None

    def test_empty_updated_content_is_rejected(self):
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(original_content=_EMBEDDINGS_MODULE, updated_content="", path=_EMBEDDINGS_PATH)
        assert exc.value.reason == "patch_empty_or_noop"

    def test_identical_content_is_noop(self):
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(
                original_content=_EMBEDDINGS_MODULE,
                updated_content=_EMBEDDINGS_MODULE,
                path=_EMBEDDINGS_PATH,
            )
        assert exc.value.reason == "patch_empty_or_noop"

    def test_non_py_file_skips_parse_and_symbol_checks(self):
        # A .yaml file with "broken python" syntax but a benign real change passes
        # the parse/symbol checks (skipped) and the size check (change is small).
        original = "\n".join(f"key{i}: value{i}" for i in range(20)) + "\n"
        updated = original.replace("key0: value0", "key0: value0-fixed")
        assert validate_patch(original_content=original, updated_content=updated, path="k8s/deploy.yaml") is None

    def test_small_file_shrink_is_allowed(self):
        # A trivial file (< 10 non-blank lines) is exempt from the size check —
        # a 3-line file legitimately becoming 1 line is not "destructive".
        assert (
            validate_patch(original_content="a = 1\nb = 2\nc = 3\n", updated_content="a = 1\n", path="tiny.txt") is None
        )

    def test_dropping_a_top_level_function_is_rejected(self):
        original = "def keep():\n    return 1\n\n\ndef also_keep():\n    return 2\n"
        # Drops also_keep — a fix must not delete a sibling top-level def.
        updated = "def keep():\n    return 99\n"
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(original_content=original, updated_content=updated, path="m.py")
        assert exc.value.reason in ("patch_removes_definitions", "patch_too_destructive")

    def test_renaming_a_method_inside_a_class_is_allowed(self):
        # Method-level (non-top-level) changes are legitimate — only module-body
        # symbols are protected. The class itself is preserved.
        original = (
            "class Widget:\n    def old_name(self):\n        return 1\n\n    def helper(self):\n        return 2\n"
        )
        updated = (
            "class Widget:\n    def new_name(self):\n        return 1\n\n    def helper(self):\n        return 2\n"
        )
        assert validate_patch(original_content=original, updated_content=updated, path="w.py") is None
