"""One-off helper to freeze the current production prompts as v1 baselines.

Usage (from the api-v2.0 directory, no Django setup required):
    python components/agents/tests/prompt_eval/prompts/_freeze.py

Parses each source module via ``ast`` and writes the named string
constant as a sibling .txt file in this directory. Re-run when bumping
versions (e.g. v1 → v2 after a successful eval-driven iteration).

The frozen .txt files are archival — they let
``diff prompts/foo_v1.txt prompts/foo_v2.txt`` show what changed when
chasing a score regression or recovering an older prompt for rollback.
The planner's runtime catalog substitution is NOT included; the
template form is what's frozen, which is what the prompt-author
maintains by hand.

Pytest does not collect this module (underscore prefix).
"""
from __future__ import annotations

import ast
from pathlib import Path

# (source_relative_path, constant_name) → output filename
EXTRACTS: list[tuple[str, str, str]] = [
    (
        "components/agents/infrastructure/adapters/langchain/deep/llm_planner.py",
        "SYSTEM_PROMPT_TEMPLATE",
        "planner_system_v1.txt",
    ),
    (
        "components/agents/infrastructure/adapters/langchain/deep/llm_planner.py",
        "PROJECT_SYSTEM_PROMPT",
        "planner_project_v1.txt",
    ),
    (
        "components/agents/infrastructure/adapters/langchain/deep/llm_planner.py",
        "TASK_SYSTEM_PROMPT",
        "planner_task_v1.txt",
    ),
    (
        "components/agents/infrastructure/adapters/langchain/tools/project_estimator.py",
        "SYSTEM_PROMPT",
        "estimator_system_v1.txt",
    ),
    (
        "components/agents/infrastructure/adapters/langchain/tools/project_estimator.py",
        "REPAIR_PROMPT",
        "estimator_repair_v1.txt",
    ),
    (
        "components/agents/tests/prompt_eval/graders/model/planner_judge.py",
        "GRADER_SYSTEM_PROMPT",
        "grader_planner_judge_v1.txt",
    ),
]


def _extract_constant(source_path: Path, name: str) -> str:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                raise SystemExit(
                    f"{source_path}:{node.lineno}: {name} is not a string literal"
                )
    raise SystemExit(f"{source_path}: {name} not found")


def main() -> None:
    # __file__ is at components/agents/tests/prompt_eval/prompts/_freeze.py.
    # parents[4] is the api-v2.0 root.
    here = Path(__file__).resolve().parent
    root = here.parents[4]
    for rel, name, filename in EXTRACTS:
        source = root / rel
        content = _extract_constant(source, name)
        out = here / filename
        out.write_text(content, encoding="utf-8")
        print(f"wrote {out.relative_to(root)}: {len(content)} chars")


if __name__ == "__main__":
    main()
