# Pin Versions — Never `:latest`, Never Unpinned (HARD RULE)

autosec is a **security tool**: it pulls and runs third-party images (scanner engines like Trivy and
Prowler) against customers' environments, and ships software customers trust. An unpinned dependency
is a supply-chain hole — `:latest` (or a floating range) can change under you at any time, including
to a broken or **compromised** build, with no diff, no review, and no reproducibility. So we pin,
always. This is not optional for a security product.

## The rule

1. **Never `:latest`** — nor a bare image name (which resolves to `:latest`) — for any container
   image: `Dockerfile` `FROM`, k8s manifests, scanner engine images (`TRIVY_IMAGE`, `PROWLER_IMAGE`),
   compose, CI. Pin an explicit version: `aquasec/trivy:0.58.0`, `toniblyx/prowler:5.37.0`.
2. **Pin by digest for the highest-sensitivity images** — the scanner engines that run untrusted
   work, and base images — because a version *tag* can be re-pushed. `name:tag@sha256:…` is both
   readable and immutable. A version tag is the minimum; a digest is the bar for images we execute.
3. **Pin every dependency layer:** Python (`requirements/*` with `==`, not `>=`/unpinned), base
   images, GitHub Actions (`actions/checkout@<sha>`, not `@v4`), Helm charts, apt where feasible.
4. **`:latest` is only for a throwaway local probe** (inspecting an image you're about to pin) —
   never in committed code, a manifest, or a default value.
5. **Boy-scout it:** when you touch a file with an unpinned image/dep, pin it (note the bump in the
   commit). Don't leave a `:latest` you walked past.
6. **A pin bump is a deliberate, reviewable change** — put old→new + reason in the commit so a
   version change is never invisible. Re-pin the digest when you bump the tag.

## Why this rule exists

Codified 2026-07-26 while wiring the official Prowler image: the reflex `toniblyx/prowler:latest`
would mean every scan silently runs whatever was last pushed to that tag — unacceptable for a tool
whose whole job is security. Henry: *"never use :latest tags — start the habit of using pinned
versions; this is a security tool and we need to be very careful."*

## Cross-references

- `no-shortcuts.md` — a floating version is a shortcut that defers a supply-chain decision.
- `improve-dont-replicate.md` — when you touch unpinned inherited config, fix it as you see it.
- `.claude/skills/architecture/SKILL.md` — scanner engines are driven adapters we pull + run; pin them.
- CLAUDE.md — "Security posture is first-class (this will be probed by hackers)".
