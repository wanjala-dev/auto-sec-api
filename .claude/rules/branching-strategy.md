# Branching Strategy

## Branch Hierarchy

```
main                    ← production-ready, protected
  └── development       ← integration branch, all feature work merges here first
        └── fix/*       ← bug fixes
        └── feat/*      ← new features
        └── refactor/*  ← refactoring work
```

## Rules

1. **Always branch from `development`**, never from `main`.
2. **PRs target `development`**, not `main`. Merges to `main` happen separately after QA.
3. **Branch naming**: `fix/<short-description>`, `feat/<short-description>`, `refactor/<short-description>`.
4. **One concern per branch** — don't bundle unrelated fixes. Each PR should be reviewable in isolation.
5. **Never force-push to `development` or `main`**.

## Workflow

```bash
git checkout development
git pull origin development
git checkout -b fix/receipt-amount-conversion
# ... make changes, test, commit ...
git push -u origin fix/receipt-amount-conversion
gh pr create --base development
```

## Worktrees

Same rules apply to `git worktree` — every worktree is a branch in its own directory, so the branching rules above carry over.

1. **Always create a worktree off `development`, on a new feature branch.** That way the work merges back to `development` via PR like any other branch:
   ```bash
   git fetch origin
   git worktree add .claude/worktrees/<short-name> -b feat/<short-name> origin/development
   ```
2. **Never base a worktree directly on `development` itself.** Git enforces "one branch checked out in one place at a time" across all worktrees in the repo — if a worktree owns `development`, the primary clone gets bumped to a different branch (or detached HEAD) and `git pull` / `./manage-ec2.sh deploy` from there will silently ship the wrong commit. The 2026-06-09 EC2 budget outage happened this way: a worktree owned `development` while the primary clone sat on a stale `chore/worktree-off-development-rule` branch, and the deploy shipped that stale commit even though the fix was already merged. **The primary clone must always be on `development` at `origin/development`'s tip.** `manage-ec2.sh` now refuses any deploy that violates this, but the operator must still actively sync.
3. **Never base a worktree off `main`.** Same reason PRs target `development`: feature work integrates there first.
4. **Tear the worktree down when its PR merges:**
   ```bash
   git worktree remove .claude/worktrees/<short-name>
   ```
   Stale worktrees pile up, hold branches hostage, and clutter `git status` in the main clone.
5. **Periodically prune** to clean up worktrees whose directories were deleted manually:
   ```bash
   git worktree prune
   ```
