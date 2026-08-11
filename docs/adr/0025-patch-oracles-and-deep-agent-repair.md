# ADR 0025 — Validate the patch, and let the specialist READ the code

Status: accepted (Phase 1 built; Phase 2 decided, not built)
Date: 2026-08-11
Supersedes nothing. Extends ADR 0019 (SAST) D5.

## Context

The draft-PR loop closes end to end (#321, #322, #323). What it closes WITH is not
trustworthy. Of five patches produced against real repositories:

| PR | patch | verdict |
|---|---|---|
| 866 | `cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))` | wrong — identifier bound as a value |
| 869 | `cursor.execute('CREATE SCHEMA IF NOT EXISTS %s', [schema])` | wrong — same error, independently |
| 867 | `jwt.decode(id_token, '', algorithms=['ES256'], options={'verify_signature': True})` | wrong — verification against an empty key |
| 870 | `jwt.decode(id_token, settings.SOCIAL_AUTH_APPLE_PUBLIC_KEY, algorithms=['RS256'])` | plausible, unverified |
| 325 | `cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))` | correct |

Two rounds of prompt work (#324 rule-specific guidance, #326 un-pasteable exemplars)
did not fix it. The measured result after both: of four re-triaged findings, one
reproduced the original wrong shape and three produced NO patch at all.

### What the research says

[Why LLMs Fail (arXiv 2603.10072)](https://arxiv.org/html/2603.10072v1), 319 security
patches: **24.8% fully correct**; **51.4% "semantic misunderstanding"** — syntactically
valid code applying a fundamentally incorrect repair strategy; **10.3% functional but
still exploitable** ("the most dangerous failure mode" — it passes CI). Our observed
rate sits on that line, so this is the state of naive LLM patching, not a local defect.

Decisively, the outcome distribution is **bimodal**: only **0.3%** of patches land
near-correct. There is no near-miss band for a better instruction to close, and the
paper's explicit recommendation is to **reject iterative refinement** and invest in
validation instead — PoV tests, not prompt tweaks. [TerraProbe (arXiv 2606.26590)](https://arxiv.org/pdf/2606.26590)
reaches the same conclusion for LLM-assisted infrastructure code via layered oracles
(syntactic → semantic → behavioural → domain-specific).

### What we found in our own code

The advisor is a **single direct LLM call** (`SastFixAdvisor.suggest` →
`self._get_llm().chat`). It is hosted by a LangChain agent but is not a deep-agent
run: no planner, no tool loop, no RubricMiddleware. And the `code_security_agent`'s
seven tools — rank repos, scan status, scan history, get findings, list pending,
triage, open PR — include **no repository read at all**. `read_repo_file` exists in
the integrations context but is only used internally, to fetch a fixed window around
the flagged lines.

So the specialist cannot search the codebase. Asked to verify a JWT signature, it
cannot go and find where that project keeps its issuer key — the fact the fix
depends on. It either invents a helper (`fetch_jwks_key`, PR-era #326 measurement)
or declines. **Both failures are the tool inventory, not the prompt.**

## Decision

### Phase 1 — deterministic oracles (built)

Validate the patch rather than coax the model. Three oracles run before any patch is
called verified, cheapest first, on whatever produced it:

* **L0 — is there a patch at all.** Guidance is not an artifact. Three live findings
  shipped `verified` with an empty `fix_after`, because the grounding check only ever
  graded prose. Exempt for `guidance_only` classes, where prose IS the artifact.
* **L1 — does it still parse.** 13.2% of LLM security patches do not compile.
  Comparative and conservative: fail only when the code being replaced parses and the
  replacement does not. Python only — the one parser in this image. An oracle that
  cries wolf gets muted.
* **L3 — does it reproduce a known-wrong shape** for its remediation class (ADR 0019
  D5 anti-patterns). This is the one mechanism that has worked consistently: it caught
  the identifier-binding bug every time it appeared.

**L2 — re-scan the patched content with the same rule** — is the highest-value oracle
we do not yet have. It requires the opengrep scan-Job substrate (the binary ships in
`autosec-opengrep`, not the app image), so it is deferred rather than faked.

Also decided here: **repair strategy is per remediation class** ("CWE-aware routing"
in the paper's terms; fix rates range 0%–45% by weakness). `guidance_only` classes
produce no patch and say so, instead of shipping an empty one labeled verified.

### Phase 2 — route patch generation through the deep agent (decided, not built)

The paper rejects *iterative refinement* — re-prompting the same blind call with
feedback. It does not reject *giving the model the context it lacks*, and that is our
actual gap. Auto-Sec's whole thesis is a deep-agent arm; the most important artifact
it produces is the one place we bypassed it.

Therefore: draft-PR generation routes through a **specialized code-repair agent** run
via the deep runner, so that it inherits what already exists there —
`deepagents.RubricMiddleware` grading, the DeepRun record, the per-step trace, the
LIVE RUN surface, telemetry and cost capture — and, critically, gains repository-read
tools so it can ground a fix in the code rather than in a worked example.

Required, in order:

1. **Repo-read tools on the specialist**: `read_repo_file` (exists as a service —
   expose it), plus `search_repo` and `list_repo_tree` on the `VcsPort` (the GitHub
   adapter has the tree and code-search APIs available). Read-only, allowlisted repo,
   same connection the scan already uses.
2. **Route patch generation** through `_delegate_to_agent` with
   `force_worker_agent_type="code_security_agent"` — the pinning already exists in
   `draft_fix_for_finding` and exists precisely because handing a known target to the
   LLM planner is a codified failure mode (2026-07-19).
3. **The Phase-1 oracles stay as the OUTER gate.** They are strategy-independent: they
   validate the patch, not the process that produced it. RubricMiddleware grading is
   the agent's self-check; the oracles are the deterministic floor under it.
4. **Cost and latency are the real trade.** A deep run is 10–30s of LLM calls versus
   one call today, and it must run in the `celery-ai-teammate-worker` (the daphne
   liveness incident and the 1Gi OOM are both on record). The per-repo open-PR
   throttle already caps volume, which is what makes this affordable.

## Consequences

* Wrong patches are caught deterministically instead of shipping as plausible ones;
  a finding whose class we cannot patch says so rather than producing an empty fix.
* Phase 2 makes the specialist able to answer questions it currently cannot, at a
  higher cost per finding. It must be measured against the same five-patch corpus
  before anyone claims it is better — the failure of the last two attempts was
  believing an intervention would work rather than measuring it.
* Until Phase 2 lands and is measured, SAST auto-fix stays off customer repositories
  (the standing gate on task #117).
