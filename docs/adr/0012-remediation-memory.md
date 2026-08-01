# ADR 0012 — Remediation Memory: a sign-off-gated, outcome-verified fix knowledge base the triage agent retrieves from

Status: Proposed (2026-08-01)
Relates to: ADR 0010 (the multi-provider VCS **draft-PR loop** this feeds on — its entry gate has no data
until draft PRs are being applied), ADR 0009 (the Evidence + **provenance envelope** an accepted-and-held fix
becomes), ADR 0004 (the Findings SSOT — a finding is the "question"), the `knowledge` context (pgvector RAG +
embeddings + LLM factory — the retrieval substrate), and `sign_off` (the approval gate that **is** the entry
control).

## Context

Auto-Sec's triage agent already proposes a fix and — proven end-to-end — opens a **draft pull request** to
remediate a finding. What it does *not* do is remember which of its past fixes actually **worked**. Each
triage starts cold: the agent (and the LLM behind it) reasons from scratch, so the suggested patch is only as
grounded as the base model. That is the problem this ADR closes.

**The operator pain (Tom, `docs/product/STATE_AND_VISION.md` §2.1): _"how do I know I'm shipping safely and at
scale?"_** Teams building fast with AI-written code are the ICP, and AI-written code is exactly what
hallucinates:

- **~29–45% of AI-generated code carries a security vulnerability**, and **~20% of AI-suggested packages are
  hallucinated / non-existent** ("slopsquatting" surface).[^veracode][^checkmarx] An agent that ungroundedly
  drafts a fix is drafting from the same distribution — so an ungrounded auto-fix can *introduce* the next
  finding.
- **Auto-fix-PR is now table stakes.** Snyk, Semgrep (Griffin), Mend, and Veracode all ship "AI generates a
  fix PR, a human approves it."[^veracode] So *generating* a fix PR is **not** differentiation — the market
  has commoditized it.

### This is not hypothetical — our own advisor produced a destructive patch on the very PR that proved the loop

The dogfood draft PR that proved the ADR 0010 loop end-to-end
([wanjala-dev/api-v0.2.0#828](https://github.com/wanjala-dev/api-v0.2.0/pull/828)) also produced a **bad
patch**, and it is the sharpest possible motivation for this ADR. The finding was a casing `ImportError`: the
module defines `class AIEmbeddingsProvider`, but a caller imports `AiEmbeddingsProvider`. The correct fix is a
**~1-line rename/alias**. Instead, the ungrounded advisor **deleted the entire ~50-line module** and replaced
it with a single **self-referential** import — `from …ai_embeddings_provider import AiEmbeddingsProvider` —
which imports a nonexistent name *from its own module*. That guarantees an `ImportError`, destroys the provider
registry, and breaks **every** caller.

**The draft gate + human review caught it; it was never merged — which is exactly the point.** The draft-PR
loop's human step is load-bearing precisely because the model *will* hallucinate destructively. But "a human
caught it" is not a system that improves; it is a system that stays cold and re-rolls the same dice on the next
finding. Remediation Memory is the improvement: **ground the advisor in vetted, proven fixes and put a
verification pass between the advisor and the PR**, so this class of destructive hallucination is prevented,
not just intercepted.

### What already exists (grounding — reuse, don't rebuild)

- **Findings SSOT → board.** `persist_finding_as_task` lands every finding as a board Task with provenance
  (ADR 0004). A finding is the natural "question."
- **Agent suggested-fixes.** The triage agent already produces a candidate patch per routed finding.
- **The ADR 0010 draft-PR loop — PROVEN end-to-end.** A real draft PR was opened against the monitored
  backend (PR #828) with board provenance. `OpenDraftPrUseCase`, the `GitHubConnection` + `repo_allowlist`
  consent boundary, and the triage tool exist and fire. **This is the data source Remediation Memory feeds
  on** — see *Dependency & sequencing*.
- **`sign_off` approval gate.** The workspace owner already approves high-risk agent actions — the exact
  human-in-the-loop primitive an entry gate needs.
- **pgvector RAG + embeddings + LLM factory** (`knowledge` context) — the retrieval substrate is already
  built and multi-tenant-aware.
- **Board provenance for AI actions** — every agent action already stamps a provenance event on the board.

### What's MISSING — three primitives two of Henry's older projects nailed

The gap is not more scanning or more PR-plumbing; it is a **feedback loop**. Three primitives from
`~/Desktop/codenry/codelounge` and `~/Desktop/codenry/bufferoverflowexception` map onto it directly:

1. **Rich syntax-highlighted rendering** of a fix / code excerpt — *codelounge* was a Pygments-highlighted,
   tagged snippet store; we have no first-class way to *show* a fix's code in the HUD or the PR preview.
2. **A rated / curated fix library with a "did this fix work?" loop** — *codelounge* ranked snippets by
   usefulness (a leaderboard); we throw every triage away after the PR.
3. **Preview-before-commit** — *bufferoverflowexception* let the owner **accept the canonical answer**
   (a sign-off gate) with **save-vs-preview** and search behind a service seam; we open the PR without a
   diff preview step.

### Grounding — research (what forces the four hardening decisions)

- **RAG knowledge-base poisoning is a first-class threat.** As few as **5 — in some settings a single —
  malicious documents** injected into a RAG corpus can steer **~90% of outputs** to attacker-controlled
  content.[^ragalert][^poisonarxiv][^poison2] For a *fix* library the blast radius is **insecure code pushed
  into a customer's PR** — the worst possible failure for a security product.
- **Verification layered above the model cuts hallucination.** Semgrep's Griffin keeps a **validation layer
  above the LLM**; a RAG + guardrails + validator stack cut hallucinations by **~96%** in the reported
  study.[^sast][^portkey] Retrieval **grounds**; it must never **authorize** a commit on its own.
- **Rendering code is a stored-XSS surface.** Serving syntax-highlighted code = serving HTML. Storing
  model- or user-authored *rendered HTML* is a stored-XSS vector; the OWASP guidance is to store raw and
  sanitize at render (Bleach / DOMPurify) plus a CSP.[^owasp]
- **Multi-tenant RAG leaks without per-tenant filters.** A shared index without deterministic per-tenant
  filtering leaks **~100%** cross-tenant on a targeted probe, and up to **~95% of even benign queries** leak
  via organic entity overlap.[^truto][^mavik] Isolation must be enforced at the data layer, not by prompt.

## Decision

Build a **Remediation Memory**: a **per-tenant, sign-off-gated, outcome-verified** fix knowledge base that the
triage agent **retrieves from when triaging**, so remediations are grounded in the *team's own proven fixes*
instead of the base model's hallucinations. It is composed almost entirely from parts we already own.

The composition, in the shape of the two older projects:

- A **finding** is the *question* (ADR 0004 SSOT).
- **Candidate fixes** (the agent's, the library's retrieved prior, an operator's) are *answers*.
- The **workspace owner accepts the canonical one** — this **is** the existing `sign_off` gate
  (bufferoverflowexception's "accept the answer").
- Acceptance **drives the draft PR** (ADR 0010) **and** enriches the library.
- **Preview-the-diff-before-the-PR-opens** (bufferoverflowexception's save-vs-preview) is the affordance
  between accept and open.

**The loop:** applied fixes that *work* get rated up → the agent retrieves from the vetted library at triage →
grounded, trusted remediations. An accepted + applied + held fix is simultaneously **audit evidence** (it ties
to ADR 0009's Evidence + provenance envelope) and a **board provenance event** — the board provenance fact and
the library's trust-ledger entry are the **same fact**, recorded once.

### The four hardening decisions (the security spine)

#### D1 — The entry gate IS the security control (not a UX nicety)

A fix library the agent retrieves from **is a RAG knowledge base**, so it inherits **knowledge-base
poisoning**: a single malicious "fix" in the corpus can dominate future retrieval, and here the payload is
**insecure code in a customer's PR**.[^ragalert][^poisonarxiv] Therefore corpus membership is *earned*, never
*asserted*:

> **A `RemediationEntry` may enter the retrievable corpus only when all three hold: (a) `sign_off approved`,
> (b) the draft PR was actually **applied**, and (c) the finding is observed **resolved**. There is no other
> write path.** You can only *propose* a fix; a human owner gates its entry.

This structurally **denies the injection primitive** — an attacker (or a hallucinating agent) cannot seed the
corpus without a human owner approving, a PR merging, and the finding closing. Proposal is cheap and open;
*membership* is expensive and gated. This is the same "you can only propose, a human gates" posture as the
`sign_off` and response-action frameworks. Note the concrete stakes: had the PR #828 destructive patch entered
a retrievable library ungated, the agent would retrieve *that* the next time it saw a casing `ImportError` —
the gate is what stops a bad patch from becoming a *taught* bad patch.

#### D2 — Retrieval grounds a **still-verified** candidate; the library never authorizes a commit

A retrieved entry is a **candidate**, not a decision. Before it can reach a PR it **still runs the full
verification path**: the scanner re-check plus a validating pass, exactly as a from-scratch suggestion does.
This mirrors Griffin's "verification layered above the model" and the RAG-plus-guardrails-plus-validator
result (~96% hallucination reduction).[^sast][^portkey] **The library grounds; it never straight-to-commits.**
A vetted prior that no longer verifies against *this* finding's current code is discarded like any other
failing candidate — trust in the library is never a substitute for re-verification.

**The advisor's edit step needs a verification-above-the-model guardrail — and PR #828 is why.** The
destructive patch would have been rejected by a minimal, deterministic gate that D2 formalizes and that is
worth building as a **near-term standalone fix** regardless of the full library:

- the **patched file must parse and import** (a self-referential import that guarantees an `ImportError`
  fails this immediately);
- **reject a patch that deletes the symbol the finding is about, or deletes the whole file** (deleting the
  ~50-line module to "fix" a casing typo fails this);
- **prefer a minimal, targeted diff** (a ~1-line rename/alias, not a rewrite).

Remediation Memory is exactly the composition that prevents this class of destructive hallucination:
**grounding the advisor in vetted, proven fixes (D1) + a verification pass between advisor and PR (D2).** The
guardrail above is the floor; the vetted library is the ceiling — together they replace "the human happened to
catch it" with "the system structurally couldn't ship it."

#### D3 — Store raw code + language, never rendered HTML; sanitize on render + CSP

Rendering syntax-highlighted code means **serving HTML**, which is a **stored-XSS** surface. We **do not** port
codelounge's habit of letting the model own the *rendered* HTML. Instead:

> **Store `code` (raw) + `language` only. Highlight at render time (Pygments server-side or a client
> highlighter), sanitize the output (Bleach server-side / DOMPurify client-side — the OWASP-recommended
> path), and serve under a Content-Security-Policy.**[^owasp]

Raw-not-rendered means a poisoned or malformed entry can never smuggle executable markup into the HUD or the
PR-preview surface; the highlight is a pure, sanitized, per-render transform.

#### D4 — Per-workspace, DB-filtered corpus by default

Multi-tenant RAG on a shared index leaks **~100%** cross-tenant on a targeted probe and up to **~95%** of even
benign queries via entity overlap, unless isolation is enforced below the prompt.[^truto][^mavik] Therefore:

> **The corpus is per-workspace and filtered deterministically at the DB layer — `filter(workspace_id=X)` —
> the same tenant-isolation invariant as sample-data mode (ADR 0011).** Retrieval never crosses a workspace
> boundary; the filter is a query predicate, not a prompt instruction.

A cross-tenant **"global vetted library"** (one team's held fixes helping another) is an **explicit opt-in v2,
with anonymization only** — never the default, and out of this ADR's build scope.

### Scalability

The pgvector substrate already exists (`knowledge`), so there is no new infra. The corpus is **small and
slow-growing** — **one entry per accepted + applied + resolved fix** — which makes it **self-pruning and
high-signal**: embedding cost and retrieval latency are non-issues at any realistic volume. The market is won
on **curation quality, not corpus size**; the gate (D1) is what keeps the corpus high-signal, and the gate is
also the security control. Quality and safety are the same lever.

### Why this is differentiated

Every incumbent curates at the **vendor** level — *their* dataset, *their* fix catalog, tuned across all
customers. **None productizes a per-customer feedback loop** where the **customer's own accepted-and-applied
fixes** become the grounded retrieval corpus: *"your team fixed this class of finding this way, it passed
sign-off, and it held."* That is not a named category — which makes it the wedge, and it is built almost
entirely from parts Auto-Sec already owns (Findings SSOT, sign_off, draft-PR loop, pgvector RAG, board
provenance).

## Consequences

- The triage agent's remediations become **grounded in the team's own proven fixes**, not the base model's
  guesses — directly answering Tom's *"how do I know I'm shipping safely at scale?"* and structurally
  preventing the PR #828 class of destructive patch.
- Adding the value costs a `RemediationEntry` model + an entry-gate hook on the existing sign_off/apply/resolve
  path + a retrieval step in triage + a rating loop — no new pipeline, no new store.
- An accepted-and-held fix serves triage **and** compliance (ADR 0009 evidence) **and** the board (provenance)
  from one record.

### Risks & mitigations (with honest residuals)

| Risk | Mitigation | Honest residual |
|---|---|---|
| **RAG poisoning** — malicious "fix" steers future PRs | **D1 accept-gate**: entry requires approved + applied + resolved; no other write path | A *legitimately approved* fix later found insecure can already be in the corpus — needs a **revocation** path (pull an entry when its finding reopens). |
| **Destructive advisor patch** (the PR #828 class) | **D2 verification guardrail**: patched file must parse/import; reject delete-the-symbol / delete-the-file; prefer minimal diff | The guardrail is only as strong as "parses + imports"; a patch that parses but is semantically wrong still needs the scanner re-check + human review. |
| **Stored XSS** via rendered code | **D3**: store raw + language, sanitize on render (Bleach/DOMPurify) + CSP | Sanitizer/CSP must be kept current; a client highlighter is itself dependency surface (pin per `pin-versions.md`). |
| **Cross-tenant leak** | **D4**: per-workspace deterministic `filter(workspace_id=X)` at the DB layer | The v2 global library reintroduces the risk *by design* — hence opt-in + anonymization only, deferred. |
| **Over-trust in a retrieved fix** | **D2**: retrieval grounds a candidate that **still** runs scanner re-check + validating pass | Verification is only as good as the scanner/validator; a class of finding neither can re-check is not a safe auto-apply candidate. |

## Dependency & sequencing

ADR 0012 is deliberately sequenced **after ADR 0010's draft-PR loop**: **the D1 entry gate has no data until
draft PRs are actually being applied and their findings resolved.** That dependency is **now satisfied** — the
loop is proven end-to-end (PR #828 opened with board provenance; the destructive patch it also produced is the
motivation, not a blocker). Remediation Memory is therefore buildable; it was not before.

## Non-goals

- **Not** a cross-tenant / global fix library (explicit opt-in v2, anonymized — deferred).
- **Not** an auto-apply of retrieved fixes — retrieval grounds a candidate that still runs verification and
  still passes sign-off (D2). It opens a *draft* PR; review + merge stay human (ADR 0010).
- **Not** storing rendered HTML anywhere (D3).
- **Not** a general snippet manager — the corpus is *only* accepted-applied-resolved remediations.
- **Not** replacing `sign_off` — the entry gate **is** sign_off, reused.

## Implementation plan (strangler — each phase ships on its own; this ADR is the spec, design-only)

1. **Sanitized code-render primitive.** Borrow codelounge's Pygments raw-render idea in the **D3-safe** shape
   (store raw + language, highlight + sanitize on render, CSP) to show fix code / excerpts in the HUD and in
   the **draft-PR preview** (bufferoverflowexception's preview-before-commit). Small, immediately useful, and
   independent of the library.
2. **Advisor verification guardrail (near-term, standalone).** The D2 floor: the advisor's patched file must
   parse + import; reject a patch that deletes the finding's symbol or the whole file; prefer a minimal diff.
   This alone would have blocked the PR #828 destructive patch — worth shipping before the full library.
3. **`RemediationEntry` model + entry gate.** Add the per-workspace `RemediationEntry` and populate it **only**
   on the `sign_off approved` + draft-PR-applied + finding-resolved path (D1). Link each entry to the finding's
   board provenance event (same fact, recorded once). Tenant-isolation + gate-only-write tests.
4. **Embed + retrieve-at-triage.** Embed entries via the existing `knowledge` pipeline; at triage the agent
   retrieves **top-k from the vetted, per-workspace library** (D4 DB filter) and grounds its suggestion. The
   retrieved fix **still runs verification** before it can reach a PR (D2).
5. **Rating / ranking + "did this fix hold?" outcome tracking.** The feedback loop — an applied fix that stays
   resolved ranks up; one whose finding reopens ranks down (and triggers the D1 revocation residual).
6. **Hardening.** Poisoning-resistance tests (no un-gated corpus write), tenant-isolation tests (no
   cross-workspace retrieval), XSS-sanitization tests (no executable markup survives render), and the
   preview-before-commit affordance finalized.

Build only after review. Phases 1–2 are standalone wins (a UI primitive + the guardrail that would have caught
PR #828); 3–4 stand up the grounded loop; 5 adds the feedback signal; 6 proves the security spine.

## Cross-references

- **ADR 0010** — the multi-provider VCS draft-PR loop; the *apply* half of D1's entry gate and the surface
  Phase 1's preview attaches to.
- **ADR 0009** — the Evidence + provenance envelope an accepted-and-held fix becomes.
- **ADR 0004** — the Findings SSOT; a finding is the "question."
- **`knowledge` context** — the pgvector RAG + embeddings substrate the corpus lives in.
- **`sign_off`** — the approval gate that **is** the D1 entry control, reused not rebuilt.
- **"AI actions → board provenance"** — the principle that makes the trust-ledger entry and the board event the
  same fact.

[^veracode]: Veracode — *What Is AI Code Remediation?* (auto-fix-PR as table stakes; AI-code vulnerability rate). https://www.veracode.com/security/what-is-ai-code-remediation/
[^checkmarx]: Checkmarx — *Building Trust in AI-Powered Code Generation* (vuln rate + hallucinated-package "slopsquatting"). https://checkmarx.com/learn/ai-security/building-trust-in-ai-powered-code-generation-a-guide-for-secure-adoption/
[^ragalert]: AI Alert — *RAG Knowledge-Base Poisoning: 2026 Threat Brief* (few/one malicious doc → ~90% attacker-controlled output). https://ai-alert.org/posts/rag-knowledge-base-poisoning-2026-threat-brief/
[^poisonarxiv]: *Corpus poisoning of retrieval-augmented generation* (arXiv). https://arxiv.org/pdf/2505.11548
[^poison2]: *RAG poisoning study* (arXiv). https://arxiv.org/html/2604.08304v1
[^sast]: Safeguard — *Best SAST Tools 2026* (Semgrep Griffin: verification layered above the model). https://safeguard.sh/resources/blog/best-sast-tools-2026
[^portkey]: Portkey — *Reducing AI Hallucinations with Guardrails* (RAG + guardrails + validator ≈ 96% reduction). https://portkey.ai/blog/reducing-ai-hallucinations-with-guardrails/
[^owasp]: OWASP — *Cross-Site Scripting Prevention Cheat Sheet* (store raw, sanitize on render, CSP). https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
[^truto]: Truto — *How to Architect Strict Data Isolation in Multi-Tenant RAG Pipelines*. https://truto.one/blog/how-to-architect-strict-data-isolation-in-multi-tenant-rag-pipelines/
[^mavik]: Mavik Labs — *Multi-Tenant RAG 2026*. https://www.maviklabs.com/blog/multi-tenant-rag-2026
