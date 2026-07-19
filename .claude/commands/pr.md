---
allowed-tools: Bash(git checkout *), Bash(git add *), Bash(git status*), Bash(git push *), Bash(git commit *), Bash(gh pr create *), mcp__linear-server__save_issue, mcp__linear-server__list_projects, mcp__linear-server__list_issue_labels
description: Commit, push, and open a PR
---

## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`

## Your task

Based on the above changes:

1. **SR&ED triage + Linear ticket — do this FIRST, before the git block.** Decide whether the change is
   R&D-eligible: genuine technological uncertainty (agentic RAG, deep-agent orchestration,
   reconciliation/ledger algorithms, bank-feed ingestion, structured generation) — NOT routine
   CRUD / UI / config / debug / billing. See `.claude/rules/sred-sdlc.md`.
   - **Routine work →** skip Linear entirely. Do NOT tag routine work as SR&ED. (The PR-guard hook only
     blocks R&D-*path* PRs that lack a link; a routine PR passes. If it false-positives, put
     `Linear: none` in the PR body to override.)
   - **R&D-eligible and no `SEE-` ticket exists yet →** create one via the Linear MCP
     (`mcp__linear-server__save_issue`) in the **`seed`** workspace. **Pass `team` (or `teamId`) as the
     Seed team UUID `d3aa3377-ff27-43ae-b0be-95bed2df4f56` — NOT the name "Seed"** (names are ambiguous
     across the operator's multiple Linear workspaces; the `linear_seed_guard.sh` hook rejects anything
     but the UUID). Route to the project matching the touched context:
     - `agents` / `knowledge` / RAG / planner / specialists → **Deep-Agent Orchestration & Agentic RAG**
     - budget reconciliation / ledger / currency / reports narrative → **Books-Balance & Transparency Reconciliation**
     - bank-feed / Plaid → **Bank-Feed Ingestion & Reconciliation (Plaid)**
     - writing / newsletter / report generation → **AI-Assisted Authoring — Newsletter & Report Generation**
     - a genuinely new uncertainty → create a new project
     Labels: `repo:backend` or `repo:frontend` + eligibility (`sred:review` by default, `sred:eligible`
     only if clearly algorithmic) + a phase label if obvious. **Always set `assignee = c0d3henry@gmail.com`**
     and an effort **`estimate`** (story points as a time proxy for the SR&ED salary-time record). Capture
     the new `SEE-<n>` id.
   - **R&D-eligible and a ticket already exists →** just reuse its `SEE-<n>` id.

2. Then, in a SINGLE message, do all of the git steps together:
   - Create a new branch if on main — name it `feat/SEE-<n>-<slug>` when there is a ticket.
   - Create a single commit with an appropriate message; when there is a ticket, add a `Linear: SEE-<n>`
     trailer alongside `Co-Authored-By`. (This trailer also lets `.claude/tools/sred_hours.py` auto-map the
     commit's hours to the ticket — your commits *are* the SR&ED timesheet, so don't skip it.)
   - Push the branch to origin.
   - Open the PR with `gh pr create`; when there is a ticket, include a `Linear: SEE-<n>` line in the body.

Only step 1 may use a non-git tool (the Linear MCP), and only when creating a ticket. Everything in
step 2 happens in one message of tool calls with no other text.
