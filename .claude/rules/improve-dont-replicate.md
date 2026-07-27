# Improve, Don't Replicate — Question Inherited Patterns, Fix Them As You See Them (HARD RULE)

autosec is a **fork**, and it moves fast — so most existing code is "the way it was done," not "the
way it must be done." When you touch or extend something, the trap is to **blindly copy the
established pattern** (cargo-culting the fork). Don't. Ask: *"Is this the best way, or just the way
it happens to be?"* If there's room to improve, **dig in and improve it now** — we improve things as
we see them, rather than waiting until it's too late or letting the rot compound.

## The rule

1. **Before replicating an existing pattern, question it** — especially fork-inherited code and
   "we already have a runner/adapter/pipeline for X" reflexes. A pattern that shipped once is not
   automatically the right one; it may predate a better tool, a standard format, or an ADR.
2. **When adding the Nth of something, re-examine the 1st.** The second instance is the moment to
   decide what to standardize on — or to improve the first before the pattern multiplies.
   - *Worked example:* Trivy uses the **official image + native CLI** (`trivy image --format json` →
     stdout), not a custom wrapper. Prowler was doing the opposite — a `prowler_sdk_runner.py`
     importing Prowler's **internal** SDK API ("verified in 5.36.0," i.e. it breaks on every version
     bump) inside a hand-built image. Adding Prowler as the 2nd scanner was the trigger to move it
     onto the same official-image + native-`json-ocsf` shape, not to replicate the fragile runner.
3. **Ground the improvement** (`verify-dont-guess.md`): research the current best practice online +
   via MCPs, and check it against the architecture skill / ADRs. An "improvement" that is
   unresearched or breaks a boundary is not an improvement.
4. **Improve as you see it, not "later."** "Later" is how a stale pattern becomes load-bearing and
   the cost of fixing it 10×s. If the improvement is small and in-scope, do it in the same change.
   If it's a larger rewrite, **name it and propose/flag it** — never silently leave the worse thing
   in place, and never silently balloon the scope either.
5. **Improve, don't gold-plate.** The point is fixing a *named* problem — fragile coupling, a
   superseded tool, a boundary violation, dead fork-drift — not rewriting working code for taste. If
   you can't state the concrete problem the change fixes, it isn't an improvement worth making.

## Why this rule exists

Codified when adding Prowler as the second scanner: the reflex was to replicate the fork's custom
SDK runner. Researching it — the way the Trivy work was researched — showed the official-image +
native-format path is stabler, maintained, and DRY-er. Henry: *"don't just blindly do it the way we
had done it — if there is room for improvement then dig into it; we are all about improving things as
we see them instead of waiting until it's too late or letting it get worse."*

## Cross-references

- `verify-dont-guess.md` — ground the improvement in research + the architecture before acting.
- `no-shortcuts.md` — the robust fix; "it works" ≠ "it's correct".
- `dry-reuse.md` — one canonical way per concern; an improvement often means converging N variants.
- `.claude/skills/architecture/SKILL.md` — "unify before you multiply"; don't add a silo.
