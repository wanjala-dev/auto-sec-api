# ADR 0034 — Dependency CVEs: scan the repo, and never ship the raw list

Status: **PROPOSED** — awaiting Henry
Date: 2026-08-21
Supersedes: nothing. Relates to ADR 0013 (contextual risk), ADR 0019 (code scanning),
task #146 (reachability), task #144 (bulk suppress).

## Context

Henry asked whether we can list and scan dependency CVEs the way GitHub's Dependabot
does, and surface them as ordinary findings.

We cannot today. Everything below was measured or read, not recalled.

### What we actually run (verified 2026-08-21)

Trivy is invoked in exactly one mode, in
`components/container_security/infrastructure/adapters/trivy_scanner.py`:

```sh
trivy --cache-dir "$TRIVY_CACHE_DIR" --timeout {timeout} image --format json …
```

`image` mode finds CVEs in OS packages and in language packages **installed inside a
built image**. The SAST path (`code_security`, Opengrep) is pattern-matching over
source and has no concept of a CVE.

**There is no overlap to trade against.** Trivy's `image` mode does not read
`package-lock.json` or `requirements.txt` at all — those are picked up only by
filesystem/repo scanning ([Trivy docs](https://trivy.dev/docs/latest/guide/target/filesystem/),
[aquasecurity/trivy#4769](https://github.com/aquasecurity/trivy/discussions/4769)). An
earlier draft of this analysis assumed a containerised repo would already be covered
via its image. That assumption was wrong, and it was the assumption that made the gap
look smaller than it is.

### What is actually connected (verified against the live cluster)

Two VCS connections, both GitHub, both `wanjala-dev`:

```
ALLOWLIST 2965557b ['wanjala-dev/api-v0.2.0']
ALLOWLIST cc287133 ['wanjala-dev/api-v0.2.0', 'wanjala-dev/literacyseed',
                    'wanjala-dev/wanjala-claude-kit', 'wanjala-dev/auto-sec-api',
                    'wanjala-dev/auto-sec-frontend', 'wanjala-dev/auto-sec-infra']
```

**No customer repository is connected.** The question "do Tom's or Isaac's repos have
lockfiles we would catch" cannot be answered from the system — we are dogfooding on our
own code and nothing else. That is worth stating plainly rather than reasoning past:
any claim here about customer value is a hypothesis, not an observation.

Our own repos do carry real lockfiles — `auto-sec-api/requirements/*.txt` (pinned with
`==` per `pin-versions.md`) and `auto-sec-frontend/package-lock.json` — so the scan
would find genuine material immediately. As a build target that is enough. As
validation it is not.

### What the field says

Reachability analysis — asking whether the vulnerable *function* is callable, rather
than whether the vulnerable *library* is present — removes **92–98%** of SCA findings:
Endor Labs reports 95% noise reduction via call-graph analysis and 92% at function
level; Semgrep reports up to 98% on high/critical
([Endor](https://www.endorlabs.com/use-case/reachability-sca),
[Semgrep](https://semgrep.dev/blog/2025/what-you-should-know-about-dependency-reachability-in-sca/),
[nhimg](https://nhimg.org/articles/reachability-analysis-in-sca-cuts-alert-noise-and-focuses-triage/)).

More than **40%** of alerts from security tools are false positives
([2022 Cloud Security Alert Fatigue Report, via VMware Tanzu](https://blogs.vmware.com/tanzu/reduce-noise-from-false-positives-in-your-trivy-cve-report/)).

Trivy natively consumes VEX to suppress non-applicable CVEs with a machine-readable
justification ([Trivy filtering](https://trivy.dev/docs/latest/configuration/filtering/)).

## The decision that matters

Read those numbers next to our own operator feedback and they say the same thing from
opposite directions.

Tom's #1 request was **"a single actionable digest, not a wall of findings."** William
independently said the same. A dependency scan with no prioritisation is the canonical
wall — it is precisely what Dependabot is disliked for, and reachability research exists
because 92–98% of those rows are not worth a human's attention.

So the risk here is not that we fail to build SCA. It is that we build it *correctly*,
ship the raw list, and hand our two best design partners the exact artefact they told us
they did not want — with our name on it instead of GitHub's.

**D1 — We scan the repo.** `trivy fs` behind the existing `ScannerPort`, on the scanner-Job
spine, reusing the repo archive the SAST path already fetches at a resolved commit SHA.
Same pinned image, same adapter shape. It is a mode, not a new tool or a new pin.

**D2 — The raw list is never the default view.** Findings land in the SSOT as ordinary
findings, but the default filter is KEV-listed or high-EPSS. The full list stays one
click away and is labelled as such. We already have EPSS/KEV (ADR 0013, task #64), so
this costs a filter rather than a subsystem, and it is the whole difference between a
digest and a wall.

**D3 — Reachability is the real answer and is NOT in this phase.** Task #146 remains the
moat. D2 is the cheap 80% that makes D1 shippable without it; it is not a substitute,
and this ADR should not be read as claiming it is.

**D4 — Ingesting Dependabot alerts is rejected as the primary.** We have the GitHub App,
and pulling existing alerts via the API is cheaper than scanning. But it is GitHub-only
and requires the customer to have Dependabot enabled — so it cannot be the mechanism a
provider-neutral product depends on. Worth revisiting later as enrichment, where their
triage state is a signal we do not otherwise have.

**D5 — Precision caveat, stated because it will bite.** Trivy reads non-lock manifests
(`requirements.txt`) even when a lockfile exists, and those may not pin exact versions
([Chainguard](https://edu.chainguard.dev/chainguard/chainguard-images/staying-secure/working-with-scanners/trivy-tutorial/)).
Our own requirements are `==`-pinned so we will not see this; a customer with loose pins
will, and the finding must say the version was inferred rather than read. A CVE reported
against a version we guessed is worse than no finding.

## Consequences

- A dependency CVE becomes an ordinary finding: on the board, in ALERTS, in the BRIEF,
  triageable by the same agent, remediable by the same draft-PR loop. A dependency bump
  is a far more mechanical patch than a SAST fix and is plausibly the highest-confidence
  auto-PR we could ship.
- We will be scanning **our own repos only** until a customer connects one. Everything
  this produces before then is dogfood, and should be described that way internally.
- Sequencing: D1+D2 together, roughly two days. The draft-PR loop after that, one more.
  Shipping D1 without D2 is explicitly rejected.

## Open questions for Henry

1. **Is this ahead of reachability (#146)?** SCA + EPSS/KEV is days; reachability is
   weeks but is the actual differentiator. My read: do this first *because* it produces
   the corpus reachability would later filter — but that is a judgement about sequencing,
   not a fact.
2. **Do we want the Dependabot-alert ingest at all**, given D4, or is provider-neutral
   scanning the only path we maintain?
3. **Is dogfooding enough to start?** No customer repo is connected. We can build against
   our own, but we will not learn whether the ranking is right until someone else's
   dependency tree is in front of us.
