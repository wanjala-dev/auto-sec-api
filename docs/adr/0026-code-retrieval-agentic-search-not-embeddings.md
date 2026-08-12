# ADR 0026 — Read the customer's code, never keep it: agentic search over embeddings

Status: accepted
Date: 2026-08-11
Extends ADR 0025 (patch oracles + deep-agent repair). Constrains ADR 0012 (Remediation Memory)
and the `knowledge` context's retrieval surface.

## Context

ADR 0025 established that the SAST specialist could not read the project it was fixing, and
PR #332 gave it three read-only tools — `search_repo`, `read_repo_file`, `list_repo_tree` —
resolved live through the VCS API inside the scan's existing consent boundary.

The obvious next question is whether we should instead **index** each connected repository into
our pgvector store and let the deep agent retrieve over it — an agentic-RAG layer for code. We
already own every part needed: pgvector, an embeddings port, a retrieval tool on every agent. It
would be a small build. This ADR records why we are not going to do it.

### What the field found

The industry ran this experiment and reversed.

* **Anthropic removed vector search from Claude Code** in May 2025 — embedding pipeline, local
  vector database and chunking heuristics deleted in favour of grep. Boris Cherny: *"It
  outperformed everything. By a lot, and this was surprising."*
  ([Claude Code Doesn't Index Your Codebase](https://vadim.blog/claude-code-no-indexing/))
* **Cursor hired the engineers behind that decision**, and Windsurf, Cline, Devin and Sourcegraph
  Amp dropped vectors for tool-driven search.
* **Amazon Science (AAAI 2026)** measured agentic keyword search at **94.5% of RAG faithfulness
  with zero vector store**.
* Repository-level survey work reaches the same place
  ([arXiv 2510.04905](https://arxiv.org/pdf/2510.04905),
  [arXiv 2605.27123](https://arxiv.org/html/2605.27123v1)).

Four reasons, each of which binds here:

1. **Precision.** Code is exact identifiers. Embeddings return fuzzy positives; `fetch_jwks_key`
   either exists in a repo or it does not.
2. **Freshness.** An index drifts from the code. For us that is not cosmetic — we ground fixes at
   a specific scanned SHA, so a stale index produces a *wrong patch*, the exact defect ADR 0025
   exists to stop.
3. **Simplicity.** No index to build, invalidate or reconcile per tenant per push.
4. **Iteration.** The agent refines its own query, follows imports and self-corrects — which is
   what the deep run plus RubricMiddleware (#330, #331) now make possible.

Our workload is also the most search-favourable shape there is. A SAST finding arrives with rule,
path, line and snippet already known. The open question is *"where does THIS project define its
issuer key?"* — exact retrieval, not semantic similarity.

### The factor that actually decides it

Performance is not the binding constraint. Data custody is.

**Embedding inversion reconstructs 92%+ of the original text from stored vectors — embeddings are
not an anonymization technique**
([Vector Database Leakage](https://sec.co/blog/vector-database-leakage-risks)). An index of
customer repositories would make our pgvector store a *reconstructable copy of every customer's
proprietary source code*. Separately, vector databases holding embeddings of regulated data are in
scope for **SOC 2, HIPAA and the EU AI Act regardless of where the raw documents live**, and SOC 2
Type II now expects query-level access logs on the vector store
([RAG compliance guidance](https://beyondscale.tech/blog/vector-database-security-rag-compliance-monitoring)).

Auto-Sec's posture is read-only, least-retention: we do not mutate a customer's cloud
(`SOC_RESPONSE_READ_ONLY`), we hold findings rather than payloads. "We keep a semantically
searchable copy of your codebase" is a different company with a different threat model, and it is
the worst breach headline available to a security vendor. Cursor can carry that risk because
indexing *is* their product. For us it would be a side effect of a fix-quality feature.

### The honest cost trade

Indexing is cheaper at **inference** (one retrieval call instead of several agent round-trips);
search is cheaper at **maintenance** (no embedding spend, no invalidation, no staleness bug class,
no new attack surface). Our volume settles it: the per-repo throttle caps open draft PRs at 3,
`MAX_ITERATIONS_CAP` is 2, and triage runs in a background Celery worker where latency is nearly
free. We are far from the scale where extra round-trips hurt.

### The real weakness in what we shipped

`search_repo` depends on **GitHub's** code-search index, which covers the default branch, carries
indexing lag, sits on its own rate limit, and on 2026-04-01 was fully unavailable for 2h20m with
100% of queries failing and stale results for hours after
([GitHub availability report](https://github.blog/news-insights/company-news/github-availability-report-april-2026/)).
So our search is weaker than a local `ripgrep`, and can be stale *relative to the commit we
scanned* — which matters precisely because we ground fixes at a SHA.

The answer to that is not embeddings. The opengrep scan Job already checks the repo out at the
scanned SHA; an index built there is exact, correctly-versioned, rate-limit-free and disposable.

## Decision

1. **Agentic search is the primary code-retrieval path.** The specialist reads the customer's
   code through tools at run time (`search_repo` / `read_repo_file` / `list_repo_tree`), inside
   the scan's `repo_allowlist` consent boundary, and never from a copy we keep.

2. **We do not persist embeddings of customer source code.** No repository indexing into pgvector
   or any vector store, for retrieval or any other purpose. This is a security-posture commitment,
   not a performance preference — it is answerable in a procurement questionnaire and it does not
   expire when the build gets inconvenient. Reversing it requires a new ADR that addresses
   inversion, tenant isolation, retention and the SOC 2 evidence burden explicitly.

3. **If live search proves insufficient, the escalation is a STRUCTURAL index, not a vector one** —
   a tree-sitter symbol/outline map built inside the existing scan Job at the scanned SHA, stored
   as a scan artifact under the same retention as the SBOM (ADR 0022's artifact channel), and
   exposed as one more read tool. Deterministic, invertible-by-nature (it is derived structure,
   not a lossy embedding of the text), fresh by construction, and disposable with the scan.

4. **Agentic RAG is pointed at OUR data, not the customer's source.** The corpora that justify
   semantic retrieval are:
   * **Remediation Memory** (ADR 0012) — "have we approved a fix for this class before?" is a
     genuinely fuzzy question over a per-tenant, sign-off-gated store we own.
   * **Findings / assets / vuln-intel** — and this is currently broken: `retrieve_workspace_context`
     is attached to all nine agents while its corpus is still the fork-inherited **nonprofit
     snapshot**, so no finding, asset, scan or CVE is indexed. Every agent carries a retrieval tool
     that cannot return security signal. Fixing that outranks adding a second retrieval system.

5. **Measure before escalating.** Route the patch advisor through the deep run (ADR 0025 Phase 2
   part 2), then re-measure the five-patch corpus. Only a measured shortfall justifies step 3 —
   the failure of the two prompt-tuning rounds was believing an intervention would work rather
   than measuring it.

## Consequences

* The specialist's reach is bounded by what the VCS API can answer, and inherits GitHub code
  search's freshness and availability characteristics. Accepted deliberately; step 3 is the
  escape hatch if measurement shows it binds.
* We keep the option to serve customers who would refuse a vendor that stores their source. For
  the security-tooling ICP that is a feature, and worth saying out loud in sales material.
* pgvector stays scoped to data we own. The blast radius of a breach of our store does not include
  customer source code.
* The nonprofit-corpus gap becomes a named, prioritized defect rather than ambient fork drift.
* If a future arm genuinely needs semantic code retrieval (an "explain this codebase" surface
  rather than a "fix this finding" one), it arrives as a new ADR with the custody question answered
  first, not as an incremental extension of this pipeline.
