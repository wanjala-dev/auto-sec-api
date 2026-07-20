"""
Service-layer entrypoints for deep agent orchestration.

Current state:
- Provides a helper to run a PlanSpec through a single agent type (using the runner).
- Planner is expected to be provided by the caller (LLM-backed planner TODO).
- Checkpointing defaults to in-memory; swap to DB-backed when available.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.infrastructure.adapters.langchain.deep.packs import get_deep_pack

try:
    from infrastructure.persistence.workspaces.models import Workspace
except ImportError:  # pragma: no cover
    Workspace = None


def _resolve_domains_and_pack(workspace_id: str, requested_pack: str | None) -> tuple[tuple[str, ...], str | None]:
    """
    Resolve the workspace's security-domain slugs for planner context.

    The wanjala-era Sector FK (whose config could override the deep pack) was
    replaced by the domains M2M in the sectors→domains rename. Domains are pure
    classification (Cloud, Endpoint, …) with no config, so the caller-provided
    deep pack always stands; the slugs ground the planner in what the
    workspace actually operates across.
    """
    if not Workspace or not workspace_id:
        return (), requested_pack
    workspace = Workspace.objects.filter(id=workspace_id).prefetch_related("domains").first()
    if not workspace:
        return (), requested_pack
    slugs = tuple(str(d.slug) for d in workspace.domains.all() if getattr(d, "slug", None))
    return slugs, requested_pack


def _merge_planner_context(
    extra_context: dict[str, Any] | None,
    *,
    domain_slugs: tuple[str, ...],
    deep_pack: str | None,
) -> dict[str, Any]:
    context = deepcopy(extra_context or {})
    if domain_slugs:
        context.setdefault("domains", list(domain_slugs))
    if deep_pack:
        context.setdefault("deep_pack", deep_pack)
    return context


def _rerank_min_score_from_env() -> float | None:
    """Read ``KNOWLEDGE_RERANK_MIN_SCORE`` from the environment.

    Returns ``None`` (the no-filter sentinel) when the env var is
    unset or malformed — production behavior is unchanged unless
    explicitly opted in.  Non-numeric values silently fall back
    to ``None`` rather than 0.0 because 0.0 is now a real
    (aggressive) threshold for cross-encoder MS-MARCO logits,
    not the "no filter" sentinel it used to be.  Any float
    (positive OR negative) is accepted — see the reranker use
    case docstring for why negative thresholds matter on the
    workspace-snapshot corpus (task #84).
    """
    import os

    raw = os.environ.get("KNOWLEDGE_RERANK_MIN_SCORE", "")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _prefetch_pdf_scoped_context(
    *,
    workspace_id: str,
    pdf_id: str,
    goal: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve top-k chunks from a single PDF via the default vector store.

    Mirrors the filter shape ``PdfChatUseCase`` uses (``pdf_id`` +
    ``workspace_id``) but goes through ``AIVectorStoreProvider`` so the
    adapter is environment-driven (pgvector / Elasticsearch / etc.) —
    same dynamic-providers pattern documented in the project CLAUDE.md.

    Returns the serialised chunk list the planner expects (matches
    ``_prefetch_retrieved_context``'s shape so the citations panel
    renders identically). Empty list on any failure so a flaky retrieve
    never blocks the chat from rendering an answer.
    """
    try:
        from components.knowledge.application.ports.vector_store_port import (
            SearchMode,
        )
        from components.knowledge.application.providers.ai_vector_store_provider import (
            AIVectorStoreProvider,
        )

        vector_store = AIVectorStoreProvider().get_port()
        chunks = vector_store.hybrid_search(
            goal,
            k=k,
            filters={"pdf_id": pdf_id, "workspace_id": workspace_id},
            mode=SearchMode.HYBRID,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Failed to prefetch PDF-scoped context for pdf=%s workspace=%s",
            pdf_id,
            workspace_id,
        )
        return []

    serialised: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = chunk.metadata or {}
        serialised.append(
            {
                "section": metadata.get("section") or metadata.get("page") or "",
                "section_title": metadata.get("section_title") or metadata.get("title") or "",
                "content": (chunk.content or "").strip(),
                "score": round(chunk.score, 4) if chunk.score else 0.0,
                # SEE-200 — surface the index-time injection flag so the
                # planner's untrusted-content grounding rule can see it.
                "untrusted": bool(metadata.get("untrusted")),
                "pdf_id": pdf_id,
            }
        )
    return serialised


def _prefetch_retrieved_context(
    *,
    workspace_id: str | None,
    goal: str,
    k: int = 5,
    pdf_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch top-k indexed chunks for *goal*, optionally scoped to a PDF.

    Returns an empty list on any failure — the planner can still run
    without grounding, it will just produce less specific plans.  Errors
    are logged via the standard adapter logger.

    When ``pdf_id`` is set, retrieval is scoped to chunks from that
    specific PDF (matches ``PdfChatUseCase``'s filter shape:
    ``{pdf_id, workspace_id}`` against the vector store). This is the
    path the unified chat surface takes when the user opens a PDF
    conversation from the library — the Deep Agent planner gets only
    that PDF's content as grounding, so the answer is anchored to the
    document the user asked about rather than the whole workspace.

    When ``pdf_id`` is unset, retrieval falls back to the
    workspace-snapshot scope (``workspace_retrieval()``) — same as
    before this PDF wiring landed.

    Tier 3 #9 — the goal is rewritten via the LLM query rewriter
    before being passed to the vector store.  ``"tldr"`` becomes
    ``"workspace mission summary recipients donors active campaigns"``,
    which lands closer to the snapshot chunks under cosine similarity.
    Rewriting is cached per ``(workspace_id, goal)`` and falls back
    to the raw goal on any error.

    Tier 3 #10 — over-fetch then rerank.  Ask pgvector for ``k * 4``
    chunks under cosine, then a cross-encoder reranker re-scores
    them against the *original* goal (not the rewritten query) and
    returns the best ``k``.  Reranker errors / missing model falls
    back to the original cosine order truncated to ``k``.

    Tier 3 #12 — when ``KNOWLEDGE_SELF_VERIFY_ENABLED`` is set,
    wrap the search in an iterative loop: LLM scores chunk
    sufficiency against the goal, and on insufficient results
    reformulates the query and re-searches (up to 3 rounds).
    Disabled by default — the extra LLM round-trips per planner call
    are real cost; turn on per environment.
    """
    if not workspace_id or not (goal or "").strip():
        return []
    if pdf_id:
        return _prefetch_pdf_scoped_context(
            workspace_id=str(workspace_id),
            pdf_id=str(pdf_id),
            goal=goal,
            k=k,
        )
    try:
        from components.knowledge.application.providers.workspace_retrieval_provider import (
            workspace_retrieval,
        )
        from components.knowledge.application.use_cases.iterative_retrieval_use_case import (
            IterativeRetrievalUseCase,
            is_self_verify_enabled,
        )
        from components.knowledge.application.use_cases.rerank_retrieved_chunks_use_case import (
            DEFAULT_FETCH_MULTIPLIER,
            RerankRetrievedChunksUseCase,
        )
        from components.knowledge.application.use_cases.rewrite_query_for_retrieval_use_case import (
            RewriteQueryForRetrievalUseCase,
        )

        min_score = _rerank_min_score_from_env()

        # SEE-199 — scope the planner's grounding to the tiers the invoking
        # actor may read. Resolved once; captured by the round closure so both
        # the single-shot and iterative paths inherit it. None (no resolvable
        # role) is least-privilege → GENERAL-only.
        from components.agents.infrastructure.adapters.langchain.base import (
            resolve_workspace_role,
        )

        viewer_role = resolve_workspace_role(user_id, workspace_id)

        def _single_round_retrieve(*, workspace_id: str, query: str) -> list:
            """One pass of rewrite → over-fetch → rerank.

            Closure so the iterative loop (when enabled) gets the
            same #9 + #10 pipeline per round as the single-shot path.
            ``min_score`` is the precision tuning knob from the
            ``KNOWLEDGE_RERANK_MIN_SCORE`` env var — see the use
            case docstring for the rationale.
            """
            search_query = RewriteQueryForRetrievalUseCase().rewrite(workspace_id=workspace_id, query=query)
            candidates = workspace_retrieval().search(
                workspace_id=workspace_id,
                query=search_query,
                k=k * DEFAULT_FETCH_MULTIPLIER,
                viewer_role=viewer_role,
            )
            return RerankRetrievedChunksUseCase().rerank(
                query=query,
                chunks=candidates,
                top_k=k,
                min_score=min_score,
            )

        if is_self_verify_enabled():
            chunks = IterativeRetrievalUseCase().retrieve(
                workspace_id=str(workspace_id),
                goal=goal,
                retriever=_single_round_retrieve,
            )
        else:
            chunks = _single_round_retrieve(workspace_id=str(workspace_id), query=goal)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to prefetch retrieved context for workspace %s", workspace_id)
        return []

    serialised: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = chunk.metadata or {}
        serialised.append(
            {
                "section": metadata.get("section") or "",
                "section_title": metadata.get("section_title") or "",
                "content": (chunk.content or "").strip(),
                "score": round(chunk.score, 4) if chunk.score else 0.0,
                # SEE-200 — surface the index-time injection flag so the
                # planner's untrusted-content grounding rule can see it.
                "untrusted": bool(metadata.get("untrusted")),
            }
        )
    return serialised


def run_plan_with_agent(
    plan: PlanSpec,
    *,
    agent_type: str,
    user_id: str,
    workspace_id: str,
    agent_config: dict | None = None,
    thread_id: str | None = None,
    sync_to_kanban: bool = True,
):
    """
    Execute a PlanSpec using a single existing agent type as worker.

    Planner integration is expected to be handled upstream (LLM planner TODO).

    No RAG prefetch here — this entry point runs an already-built plan,
    so the planner has already finished and grounding is the caller's
    responsibility upstream.  Workers still get ``retrieve_workspace_context``
    as a per-tool call inside the LangChain agent loop (``base.py`` injects
    it onto every agent), so they can ground individual answers; the
    planner-level prefetch only applies to ``plan_and_run_with_llm`` and
    ``plan_and_create_project`` where this service still owns plan creation.
    """
    pack = get_deep_pack((plan.metadata or {}).get("deep_pack"))
    return pack.executor(
        plan=plan,
        agent_type=agent_type,
        user_id=user_id,
        workspace_id=workspace_id,
        agent_config=agent_config,
        thread_id=thread_id,
        sync_to_kanban=sync_to_kanban,
    )


def plan_and_run_with_llm(
    goal: str,
    *,
    plan_id: str,
    agent_type: str,
    user_id: str,
    workspace_id: str,
    team_id: str | None = None,
    agent_config: dict | None = None,
    model_name: str | None = None,
    sync_to_kanban: bool = True,
    extra_context: dict[str, Any] | None = None,
    deep_pack: str | None = None,
):
    """
    One-shot: plan with LLM then execute with a single agent type.
    """
    domain_slugs, resolved_pack = _resolve_domains_and_pack(workspace_id, deep_pack)
    planner_context = _merge_planner_context(
        extra_context,
        domain_slugs=domain_slugs,
        deep_pack=resolved_pack,
    )
    # ``pdf_id`` lives in ``extra_context`` because PDF-scoped chat is a
    # retrieval-scope concern, not a planner-prompt concern — the
    # planner doesn't need it as a prompt field, only the retriever
    # does. ``agent_chat_use_case`` pulls it off ``Conversation.metadata``
    # and stashes it here; we pop it out before the planner_context
    # ships to the LLM so it doesn't show up as a stray prompt key.
    scoped_pdf_id = planner_context.pop("pdf_id", None) if planner_context else None
    retrieved = _prefetch_retrieved_context(
        workspace_id=workspace_id,
        goal=goal,
        pdf_id=scoped_pdf_id,
        user_id=user_id,
    )
    if retrieved:
        planner_context.setdefault("retrieved_context", retrieved)
    pack = get_deep_pack(resolved_pack)
    plan = pack.plan_planner(
        goal=goal,
        plan_id=plan_id,
        workspace_id=workspace_id,
        team_id=team_id,
        model_name=model_name,
        extra_context=planner_context,
        domain_slugs=domain_slugs,
        deep_pack=pack.slug,
    )
    state = pack.executor(
        plan=plan,
        agent_type=agent_type,
        user_id=user_id,
        workspace_id=workspace_id,
        agent_config=agent_config,
        thread_id=plan_id,
        sync_to_kanban=sync_to_kanban,
    )
    # Thread the prefetched RAG chunks back through the run state so
    # the use-case layer can persist them onto the assistant message
    # for the citations panel. The chunks already exist in
    # ``planner_context["retrieved_context"]`` but the executor's
    # state dict drops them by default — without this re-attach the
    # source-document trail dies at the planner-prefetch boundary.
    # Failure-safe: only sets the key when we actually have chunks
    # and the state is a mutable dict; non-dict states are left
    # untouched so older deep-pack contracts keep working.
    if retrieved and isinstance(state, dict):
        state.setdefault("retrieved_sources", retrieved)
    return state
