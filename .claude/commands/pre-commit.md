---
allowed-tools: Bash(pre-commit *), Bash(git status*), Bash(git diff *), Bash(pip install *), Bash(pipx install *)
description: Run pre-commit hooks on changed files (or all files if requested)
---

## Context

- Current git status: !`git status`
- Changed files (staged + unstaged): !`git diff --name-only HEAD`
- Pre-commit config: `.pre-commit-config.yaml`

## Hooks included

- **pre-commit-hooks** (v4.6.0)
  - trailing-whitespace
  - end-of-file-fixer
  - check-added-large-files
  - requirements-txt-fixer
- **gitleaks** (v8.18.4) — detect secrets and sensitive info
- **isort** (v5.13.2) — `--profile black`
- **black** (24.4.2) — `python3.11`
- **flake8** (7.0.0)
  - `--max-line-length=120`
  - `--ignore=E203,E501,W503`
  - additional dependency: `flake8-simplify`

## Your task

1. Ensure `pre-commit` is installed and the git hook is wired up (`pre-commit install` if needed).
2. Run the hooks on changed files only: `pre-commit run --files $(git diff --name-only HEAD)`.
   - If the user explicitly asked for a full repo run, use `pre-commit run --all-files` instead.
3. If any hook fails:
   - Apply the suggested fixes (many hooks auto-fix — re-stage those files).
   - Re-run the hooks until clean.
   - Report what was fixed and what still requires manual intervention.
4. Do not create commits, push, or open PRs. This command only validates and auto-fixes.
5. You have the capability to call multiple tools in a single response. Prefer parallel tool calls where independent.

## Goal

Guarantee code quality, security, and consistency across the repo before commits.
