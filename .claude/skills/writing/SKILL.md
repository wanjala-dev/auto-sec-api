---
name: writing
description: Use when working on the Writing surface — letters, updates, summaries, newsletters, blogs, templates, the unified documents library, or any AI-assisted drafting. Loads the canonical architecture for both repos. Writing is the workspace-scoped authoring + publishing surface (the "Google Docs" of the platform), backed by the `components/content` bounded context. Invoke this BEFORE writing any writing/newsletter/blog/draft code; also invoke `/architecture` before architectural changes, `/frontend-reuse` before any UI, and `/celery-tasks` before touching schedules.
---

# Writing Surface — Workspace-Scoped Authoring & Publishing

This skill provides context for the platform's Writing surface. It spans two repositories:

- **Frontend**: `/Users/henrywanjala/Desktop/frontend/literacyseed`
- **Backend**: `/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0`

The canonical plan this surface implements lives at `/Users/henrywanjala/.claude/plans/graceful-exploring-quiche.md`. Read that plan first when resuming; this skill is the durable architecture doc that keeps growing as phases ship.

---

## STATUS (2026-06-10): Foundation laid, backend domain entities next

**Decisions locked**:
1. Sidebar: nested submenu — `Workspace → Writing → Drafts, Newsletters, Blogs, Templates, Library`.
2. Bounded context: extend existing `components/content` (which already owns `News`). Move `Newsletter` from `landing` → `content`. Add `WritingDraft` + `WritingTemplate`.
3. Phasing: one merge cohort. Sequence PRs into feature branches; merge to `development` together when backend + Celery + editor + agent are in.
4. Editor: reuse `src/components/Input/TextArea/TextAreaReusable.js` (react-quill 2.0.0). No new library.
5. Gotenberg: render-only — used for "Export draft as PDF" archive. Not editor, not sender.

**Branches**:
- Backend: `writing-surface-be` at `/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0/.claude/worktrees/writing-surface-be/api-v2.0/`, off `origin/development`.
- Frontend: `worktree-writing-surface-fe` at `/Users/henrywanjala/Desktop/frontend/literacyseed/.claude/worktrees/writing-surface-fe/`, off `origin/development`.

**Architecture test baseline (2026-06-10)**: `tests/architecture/` reports **57 passing / 15 failing** on `origin/development`. The 15 failures are pre-existing — NOT regressions from this work. New code must not increase the failure count. The failing tests include `test_controller_orm_import_rules`, `test_cross_context_import_rules`, `test_explicit_architecture_naming` (entity suffix, repository suffix, handler suffix), `test_application_layer_purity`, and four context-specific application-import-rule tests. Re-run after every layer-crossing chunk:
```
docker exec compose-web-1 python -m pytest tests/architecture/ -v 2>&1 | tail -20
```
Compare pass/fail counts; investigate any new fail in *your* new file.

**Existing `components/content` layout (do not break)**:
- `api/controller.py`, `api/permissions.py`, `api/urls.py` — News CRUD + comments
- `api/requests/{category,comment,news}.py` — DRF request DTOs
- `api/resources/{category,comment,news}.py` — DRF response resources
- `application/service.py` — bare `service.py` (allowed by naming rule)
- `application/facades/document_facade.py` — exposes Elasticsearch DSL docs to other contexts (not unified-docs feed)
- `application/use_cases/__init__.py` — empty, ready for new use cases
- `application/ports/__init__.py` — empty, ready for new ports
- `application/providers/__init__.py` — empty
- `domain/errors.py` — extends shared error taxonomy (look at this before raising exceptions in new code)
- `domain/entities/` — DOES NOT EXIST yet; new entity files go here
- `infrastructure/adapters/news_documents.py` — Elasticsearch DSL Document definitions (search index, NOT unified docs)
- `infrastructure/repositories/content_repository.py` — monolithic News repo; LEAVE AS-IS, add separate repos per new entity
- `mappers/db/`, `mappers/rest/content_serializers.py`
- `workers/tasks.py` — exists, ready to extend
- `cli/management/commands/` — empty

**Phases** (track progress here):
- [x] Phase 0 — Foundation: skill, ADR, architecture-tests baseline
- [x] Phase 1 — Backend domain: entities, events, Status/Kind enums
- [x] Phase 2 — Backend persistence: models, migration (move Newsletter from landing), autodiscover shim
- [x] Phase 3 — Backend ports + repositories
- [x] Phase 4 — Backend use cases (mirror `components/reports/application/use_cases/`)
- [x] Phase 5 — Backend adapters (Gotenberg PDF, Email dispatch, LLM)
- [x] Phase 6 — Celery workers + Beat schedule, cadence config in WorkspacePreference
- [x] Phase 7 — API controllers + URLs, unified-documents port wiring
- [x] Phase 8 — `writing_agent` (ADR 0003), tools, agent_domain_map, planner carve-out
- [ ] Phase 9 — Backend tests (DEFERRED — folded into Phase 13 verification chunk)
- [x] Phase 10 — Frontend sidebar + routes (sidebar nests Writing under Workspace with 5 children; 10 routes registered including editor routes + parent redirect)
- [x] Phase 11 — Frontend pages + components + hooks + API clients (9 pages, 4 hooks, 4 API clients, WritingCard component, ComposeStartPage chooser)
- [x] Phase 12 — Cadence picker in Workspace → Settings → Reports tab (extends ReportSettingsTab with Newsletter Draft Cadence section; saves `newsletter_frequency` to WorkspacePreference alongside existing report keys)
- [x] Phase 13 — Verification: yarn typecheck clean, lint clean, /deploy-backend gate run (zero NEW failures after 3 hotfix PRs), Playwright MCP smoke on demo (PASS)
- [x] Phase 14 — PRs merged + deployed: backend #303 + #304 + #306 + #308 → development; frontend #200 + #202 → development; backend EC2 deploy + frontend CloudFront deploy (bundle hash dd1b41e1 → 04723adc); migrations applied (0001 fake-applied, 0002 forward)

## STATUS (2026-06-11): SHIPPED to demo, smoke PASS

Writing surface is live at https://d2wnv83yfoz6nw.cloudfront.net/. Backend at api.wanjala.art.

**Smoke results (2026-06-11, demo target, founder@zaylan.demo):**
- ✅ Login + dashboard landing
- ✅ `/w/<id>/writing/library` — existing AiDocumentsDirectory renders at new URL (rename works)
- ✅ `/w/<id>/writing/drafts` — EmptyStateBanner after API hit (`/workspaces/news/drafts/` returns 200)
- ✅ Compose button POSTs `/workspaces/news/drafts/`, creates draft, redirects to editor (real draft id `c1ea0980-c342-4f4d-8559-ab99c79eede7` created)
- ✅ `/w/<id>/writing/newsletters` — list page renders, API hits successfully
- ✅ Report Settings tab — "Newsletter draft cadence" section visible (cadence picker works)
- ✅ Zero console errors on writing surfaces (3 errors on Settings page are pre-existing AI-config 400s, not writing-related)
- Screenshots: `.playwright-mcp/writing-surface-newsletters.png`, `.playwright-mcp/writing-surface-cadence.png`

**Caught + fixed during deploy (5 hotfix PRs):**
- #304 — Django 6 `CheckConstraint(check=)` → `condition=` (Django 6 removed the deprecated kwarg)
- #306 — `writing_agent` missing from `DEFAULT_AGENT_TYPES` + `CANONICAL_TOOLS` (caught by 2 contract tests on the deploy gate)
- #308 — `writing_agent` missing from `ROUTING_EXPECTATIONS` (sibling contract test, fired after #306)
- #200 → #202 — Frontend API clients used `/content/...` but backend mounts under `/workspaces/news/...` (legacy mount path inherited from the News-only days of the content app)

**Round-2 polish (shipped 2026-06-11):**
- FE PR #203: blogs API path (`/news/` → `/workspaces/news/`), sidebar submenu collapse bug, abrupt compose flow (auto-create-on-?kind dropped), DraftEditorPage stuck-load Retry recovery
- FE PR #204: ComposeWizard via FormStepperLayout (kind → title+template → review → create); NewsletterGenerateModal mirroring Reports' generate flow (TabPills period preset + dates + AI guidance); TemplatesListPage rewrite with Starter/My sections + WritingTemplatePreviewDrawer (RightDrawer)
- BE PR api#314: migration `0003_seed_starter_writing_templates` — 7 starter WritingTemplates seeded (Funder thank-you, Beneficiary update, Monthly team update, Period summary, Memo, Monthly newsletter, Blog post)
- Ops: phantom test draft `c1ea0980-…` deleted from Zaylan; MinIO container/image manually removed on EC2; EBS volume grown 30GB → 50GB (`vol-0f0f0789461832747`) via `aws ec2 modify-volume` + `growpart` + `resize2fs` (no downtime); terraform variable bumped via PR demo-infra#316

**Round-3 polish (shipped 2026-06-11):**
- api#315 (chore): MinIO dropped from EC2 deploys via `profiles: ["local"]`; manually stopped on the running EC2
- demo-infra#316 (chore): EBS root volume grown 30GB → 50GB via `aws ec2 modify-volume` + `growpart` + `resize2fs` (no downtime)
- api#317 (feat): SubscriberViewSet (list / single + bulk create / delete) + AI draft endpoints (`/drafts/<id>/draft-with-ai/` + `/newsletters/<id>/draft-with-ai/`) backed by `LangchainWritingAiAdapter` that routes by kind to the matching writing_agent tool
- FE#205 (feat): SubscribersPage with Table (V1 reuse) + add modal (single + bulk paste) + remove; sidebar entry under Workspace → Writing → Subscribers; Newsletters list gets "Manage subscribers" CTA; `AskAiButton` component wired into Draft + Newsletter editors

**Follow-ups landed (2026-06-11):**
- ✅ Subscriber email rescoped to `(workspace, email)` — api#319 (merged). Migration `0004_rescope_subscriber_email_to_workspace.py` + bulk/single create paths now filter by workspace before duplicate-checking.
- ✅ URL rename `/workspaces/news/...` → `/content/...` — api#320 (merged) + FE#206 (merged). Canonical `/content/` mount added in `api/urls.py` with the `content` URL namespace; legacy mount kept for one release as a redirect-free fallback.
- ✅ Writing-agent tools wired to real LLM via `LLMFactory.create_llm` — api#321 (merged 2026-06-11 05:09 UTC). All 5 tools (`draft_newsletter_from_period`, `draft_letter`, `summarize_period`, `generate_blog_post`, `extract_key_points`) call the LLM with structured prompts; stubs preserved as fallbacks when the LLM call fails or JSON parse errors. Pairs with the `_invoke_llm` + `_extract_json_block` helpers.
- ✅ Template `{{placeholder}}` interpolation — api#322 (merged 2026-06-11 05:09 UTC). New `TemplatePlaceholderResolver` in content infrastructure substitutes `{{workspace_name}}`, `{{donations_total}}`, `{{donations_count}}`, `{{recipient_count}}`, `{{new_recipients}}`, `{{upcoming_events_count}}`, `{{program_count}}`, `{{date}}`, `{{year}}` from workspace metrics when copying a seeded template into a new draft. Unknown tokens (`{{funder_name}}`, etc.) stay literal for the editor to highlight. ORM paths corrected in api#334 (Donation / Recipient / Event resolved against the canonical model paths after the post-DDD refactor moved them).

**Round-4 polish (shipped 2026-06-11 late session):**
- api#334 (fix): `TemplatePlaceholderResolver` now resolves Donation / Recipient / Event against their post-DDD model paths (the initial #322 wiring used stale paths and silently fell back to literal tokens for those three metrics).
- api#338 (feat): `POST /content/templates/<id>/render/` — live placeholder preview. Frontend can show "what this template looks like with our data" before the user clicks Use Template. Mirrors the editor's interpolation pass so the preview matches the eventual draft body exactly.
- api#340 (feat): `BLOG` promoted to first-class `WritingDraftKind` alongside letter / update / summary / memo. Unifies the blog flow on `WritingDraft` so the same editor, the same `AskAi` button, the same export-as-PDF path serve both authoring surfaces. Legacy `News` rows surface via a read-only listing for backwards compatibility.
- api#341 (feat): Newsletter **block tree** — Reports-style structured composition foundation. AI-generated newsletters now land as a typed block tree (`HeadingBlock`, `MetricsBlock`, `HighlightsBlock`, `CallToActionBlock`, etc.) instead of opaque HTML, which makes the Preview tab + per-block regenerate possible and gives downstream tooling (RSS, social syndication) a clean schema to read.
- api#344 (feat): `force_regenerate=true` flag on newsletter generation. Operators can re-run the cadence task for a period that already has an `ai_drafted` row (the default idempotency check normally short-circuits). Used by FE#222's Regenerate button.
- FE#207 (feat): **Sponsor newsletter subscribe widget** on the org sponsorship page — closes the "donor/sponsor self-subscribe" follow-up. Public surface (no auth required) on the org's profile, POSTs to `/content/<workspace>/subscribers/` against the existing `(workspace, email)` table. The path is intentionally distinct from the admin bulk-import flow; widget rate-limited at the edge, no admin permissions inherited.
- FE#211 (feat): One-click "Use this template" → editor (skip wizard). Templates with no missing-token gaps can drop the user straight into a pre-filled draft instead of forcing the compose wizard. Wizard still triggers when the chosen template has unresolved tokens that need human input.
- FE#212 (feat): Live placeholder preview in `WritingTemplatePreviewDrawer` — calls api#338's `/render/` endpoint as the user opens the drawer, so the preview body shows the workspace's real numbers instead of `{{donations_total}}`-style placeholders.
- FE#215 (feat): Directory-driven Add Subscribers picker. Pulls the workspace's existing People directory so subscriber lists can be built from recipients / sponsors / team members already in the system, not just pasted emails.
- FE#217 (feat): Unified blog flow on `WritingDraft` + show legacy `News` rows alongside. Matches api#340 — one editor surface, mixed listing for back-compat during the transition window.
- FE#219 (feat): Reports-style newsletter **Preview tab** + block renderer. Renders api#341's block tree as the user is editing. Per-block regenerate hooks land in #222.
- FE#222 (feat): Regenerate button on newsletter editor — wired to api#344's `force_regenerate=true`. Operator can request a fresh AI pass for the same period without manually deleting the existing draft row.
- FE#224 (fix): Newsletter preview reads correctly in dark mode. Block renderer CSS classes were assuming light-theme defaults.
- FE#225 (feat): `AskAi` chat modal with tone picker + existing-body context. Replaces the single-shot Ask AI prompt with a multi-turn conversation that can see the current draft body and ride the same `writing_agent` tool dispatch path.

**STATUS (2026-06-11, evening): Writing surface complete; no tracked gaps.**

All phases shipped, all 🟡 follow-ups merged, the one unfiled follow-up (sponsor self-subscribe) shipped as FE#207. Zero open PRs on either repo touching writing/content. Next session can resume from feature-add territory rather than catching up on in-flight work. If you start fresh writing work, capture it as a new STATUS section below — don't edit history in earlier sections.

Stale worktrees worth tearing down (PRs all merged): `writing-surface-be`, `writing-followups-be`, `writing-subscribers-be`, `blog-as-draft`, `newsletter-blocks`, `newsletter-force-regen`, `template-render`, `gate-blog-newsletter`.

Related skills: `/architecture` (Explicit Architecture rules — invoke before any layer-crossing work), `/celery-tasks` (Celery rules for the dispatch task), `/frontend-reuse` (V1 component catalog), `/octopus-ui-smoke` (Playwright MCP smoke test pattern).

---

## 1. Architecture Principles (the load-bearing ones)

Every phase obeys these. They derive from CLAUDE.md HARD RULES, the Reports pipeline this surface mirrors, and the explicit-architecture rules in the `/architecture` skill.

1. **Newsletters are never auto-sent.** The Celery cadence task creates a draft Newsletter row with `status=ai_drafted`. A human reviews in the Writing UI and clicks Send. This is the unique distinction from Reports (which are auto-dispatched). Any code path that flips `status → sent` without a human action is a bug.
2. **Heavy aggregations run in Celery, never inline.** Newsletter generation pulls workspace metrics (donations, transactions, recipients, events). All aggregation happens in the Celery task. The list-newsletters view is a thin indexed read. (CLAUDE.md §6a HARD RULE.)
3. **Gotenberg is render-only.** The shared `GotenbergHtmlToPdfClient` is used to render a finalized draft to a PDF archive copy when the user clicks "Export as PDF". It is not the editor, not the email body, not the source of truth. Drafts live as HTML in the database; PDF is a snapshot.
4. **Reuse the existing react-quill editor.** `TextAreaReusable` (and `TextArea`) at `src/components/Input/TextArea/` powers grants, campaigns, events, blog (forthcoming), newsletter, drafts. Don't add Tiptap / Lexical / Slate / TinyMCE — react-quill is the platform editor.
5. **Mirror Reports, don't reinvent.** The `components/reports` context is the architectural template: `FinancialReport` + `FinancialReportRequest` + scheduled Celery dispatch + per-workspace cadence in `WorkspacePreference` + Gotenberg HTML→PDF + S3/MinIO storage + RAG indexing. Newsletter follows the same shape; deviations need a written reason.
6. **All publishing artifacts live in `components/content`.** News (blog), Newsletter, WritingDraft, WritingTemplate. Don't spawn a `writing` context — content is the right home and the architecture skill's "start as a module within an existing context" rule applies.
7. **Cross-context reads go through ports.** The `shared_platform` unified-documents controller calls `WritingArtifactsPort` exposed by `content`. It does not import `content`'s ORM models directly. (Existing `File` + `FinancialReport` direct imports in that controller are a pre-existing violation, separately flagged for cleanup.)
8. **Subscribers are owned by Newsletter; drafts are personal.** Newsletter has an M2M to Subscriber (the existing model). WritingDraft is workspace-scoped but author-owned — multiple drafts per workspace per author. Templates can be global (workspace=NULL, seeded) or workspace-owned.
9. **AI drafts via `writing_agent`, never via direct LLM calls.** Per ADR 0003 — register `writing_agent`, expose tools, map in `agent_domain_map.py`, carve scope from the catch-all planner. UI "Ask AI to draft" calls the agent endpoint, not raw model APIs.
10. **Seed templates on the backend.** Templates (Funder thank-you, Volunteer update, Monthly summary, Newsletter intro, Blog post) are seeded via Django fixtures, never hardcoded in frontend constants. (CLAUDE.md HARD RULE.)
11. **Deletes route through the recycle bin.** Drafts/newsletters/blogs delete via `TrashConfirmModal` + `useTransactionTrash` with `entityType: 'draft' | 'newsletter' | 'blog'`. Never `window.confirm()` + hard-delete.

---

## 2. Bounded Context Layout — `components/content`

Existing context. We extend it. Layout:

**File-naming HARD RULES (enforced by `tests/architecture/test_explicit_architecture_naming.py`)**:
- `domain/entities/*.py` → must end with `_entity.py`
- `infrastructure/repositories/*.py` → must end with `_repository.py`
- `application/ports/*.py` → must end with `_port.py` AND must NOT use `_repository_port.py` (mixes concerns; use `_store_port.py` for writes, `_reader_port.py` for reads). Old transitional `*_repository_port.py` files exist but new ones are rejected.
- `application/facades/*.py` → must end with `_facade.py`
- `application/handlers/*.py` → must end with `_handler.py` or `_service.py`
- `application/queries/*.py` → must end with `_query.py`
- `application/*.py` (root) → must be `service.py` or end with `_service.py`
- Errors raised in application/infrastructure layers must be domain errors that extend the shared taxonomy (see `content/domain/errors.py` for the existing context's errors).

```
components/content/
├── domain/
│   ├── entities/                          (CREATE — does not exist yet)
│   │   ├── newsletter_entity.py           (new — moved from landing)
│   │   ├── writing_draft_entity.py        (new)
│   │   └── writing_template_entity.py     (new)
│   │   (note: News entity stays informal — use existing Django model for now,
│   │    promote to domain entity in follow-up if needed)
│   ├── events/                            (CREATE)
│   │   ├── newsletter_drafted_event.py
│   │   ├── newsletter_sent_event.py
│   │   ├── draft_published_event.py
│   │   └── blog_published_event.py
│   └── errors.py                          (existing — extend with NewsletterError, DraftError, TemplateError)
├── application/
│   ├── use_cases/
│   │   ├── generate_newsletter_use_case.py
│   │   ├── dispatch_scheduled_newsletters_use_case.py
│   │   ├── create_writing_draft_use_case.py
│   │   ├── publish_writing_draft_use_case.py
│   │   ├── send_newsletter_use_case.py
│   │   └── list_writing_artifacts_use_case.py
│   ├── ports/                             (NOTE: _store_port / _reader_port, NOT _repository_port)
│   │   ├── newsletter_ai_port.py
│   │   ├── newsletter_dispatch_port.py
│   │   ├── newsletter_store_port.py       (writes — create, update status, mark sent)
│   │   ├── newsletter_reader_port.py      (reads — list, get by id)
│   │   ├── writing_draft_store_port.py
│   │   ├── writing_draft_reader_port.py
│   │   ├── writing_template_store_port.py
│   │   ├── writing_template_reader_port.py
│   │   └── writing_artifacts_port.py      (cross-context surface for shared_platform unified docs)
│   ├── providers/
│   │   └── writing_provider.py            (factory: builds ports → adapters wiring)
│   └── dto/
├── infrastructure/
│   ├── repositories/                      (one per concern, mirror components/reports pattern)
│   │   ├── newsletter_store_repository.py
│   │   ├── newsletter_read_repository.py
│   │   ├── writing_draft_repository.py    (combined — simpler entity)
│   │   └── writing_template_repository.py (combined)
│   │   (note: content_repository.py stays as-is for News)
│   ├── adapters/
│   │   ├── langchain_newsletter_ai_adapter.py
│   │   ├── gotenberg_draft_pdf_adapter.py
│   │   └── email_newsletter_dispatch_adapter.py
│   └── gateways/
├── mappers/rest/                          (extend — newsletter / draft / template serializers)
├── api/
│   ├── controller.py                      (existing — extend with NewsletterViewSet, WritingDraftViewSet, WritingTemplateViewSet)
│   ├── requests/                          (extend — newsletter.py, draft.py, template.py)
│   ├── resources/                         (extend — newsletter.py, draft.py, template.py)
│   └── urls.py                            (extend — register routes)
├── workers/
│   └── tasks.py                           (existing — extend with dispatch_scheduled_newsletters, generate_newsletter_draft, render_draft_pdf)
└── tests/
    ├── unit/
    └── integration/
```

Persistence (Django apps):
```
infrastructure/persistence/content/
├── models.py            (existing — extend)
├── tasks.py             (new — Celery autodiscover shim)
└── migrations/
    └── 00XX_writing_surface.py
```

---

## 3. Data Model

### `Newsletter` (moved from `landing`)

```python
class Newsletter(models.Model):
    STATUS_DRAFT = 'draft'          # human-authored, not yet sent
    STATUS_AI_DRAFTED = 'ai_drafted'  # cadence task produced it, waiting for review
    STATUS_SCHEDULED = 'scheduled'   # human approved, queued for send-at time
    STATUS_SENT = 'sent'             # dispatched
    STATUS_ARCHIVED = 'archived'

    id: UUID
    workspace: FK → Workspace
    title: CharField(255)
    content_html: TextField                  # the editable body
    content_payload: JSONField               # metrics snapshot for AI-drafted
    status: CharField(choices=STATUS_CHOICES)
    scheduled_for: DateTimeField (nullable)
    sent_at: DateTimeField (nullable)
    pdf_key: CharField (nullable)            # MinIO/S3 archive key
    pdf_generated_at: DateTimeField (nullable)
    subscribers: M2M → Subscriber             # preserved from landing
    author: FK → CustomUser (SET_NULL, nullable for AI-drafted)
    ai_drafted_by_agent: CharField           # 'writing_agent' for AI rows
    period_start: DateField (nullable)       # for cadence-driven rows
    period_end: DateField (nullable)
    created_at, updated_at: auto
```

State flow:
- AI cadence: `(new row, status=ai_drafted)` → human edits → `status=draft` → human clicks Send → `status=sent, sent_at=now`
- Human compose: `(new row, status=draft)` → human clicks Send → `status=sent`
- Optional scheduling: `status=draft` → "Send at..." → `status=scheduled, scheduled_for=X` → dispatch task → `status=sent`

### `WritingDraft` (new)

```python
class WritingDraft(models.Model):
    KIND_LETTER = 'letter'
    KIND_UPDATE = 'update'
    KIND_SUMMARY = 'summary'
    KIND_MEMO = 'memo'

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'

    id: UUID
    workspace: FK → Workspace
    title: CharField(255)
    body_html: TextField
    kind: CharField(choices=KIND_CHOICES)
    status: CharField(choices=STATUS_CHOICES, default=DRAFT)
    author: FK → CustomUser (CASCADE)
    template: FK → WritingTemplate (SET_NULL, nullable)
    pdf_key: CharField (nullable)
    pdf_generated_at: DateTimeField (nullable)
    ai_drafted: BooleanField (default=False)
    created_at, updated_at: auto
```

### `WritingTemplate` (new)

```python
class WritingTemplate(models.Model):
    KIND_CHOICES = (
        WritingDraft.KIND_LETTER, WritingDraft.KIND_UPDATE,
        WritingDraft.KIND_SUMMARY, WritingDraft.KIND_MEMO,
        'newsletter', 'blog',
    )

    id: UUID
    workspace: FK → Workspace (nullable — NULL = global seeded template)
    name: CharField(255)
    description: TextField
    kind: CharField(choices=KIND_CHOICES)
    body_html: TextField
    is_seeded: BooleanField                  # True for fixture-provided
    created_at, updated_at: auto
```

### `News` (existing — unchanged)

Already at `infrastructure/persistence/workspaces/news/models.py:33`. Fields: title, excerpt, body, image, media M2M (File), author, category, tags M2M, status enum (LIVE=1/DRAFT=2/HIDDEN=3), pub_date, featured.

---

## 4. Frontend Layout

### Sidebar (V1 — `src/config/sidebarSections.ts`)

Workspace section gains:
```
Workspace
├── Writing                                  (parent, default → /writing/library)
│   ├── Drafts                              → /w/<id>/writing/drafts
│   ├── Newsletters                         → /w/<id>/writing/newsletters
│   ├── Blogs                               → /w/<id>/writing/blogs
│   ├── Templates                           → /w/<id>/writing/templates
│   └── Library                             → /w/<id>/writing/library  (the existing Documents page)
├── Settings
├── Automations
└── Recycle bin
```

Teams section LOSES "Documents" — it was misfiled (always workspace-scoped, never team-scoped).

### Feature module — `src/features/writing/`

```
src/features/writing/
├── presentation/
│   ├── pages/
│   │   ├── WritingLibraryPage.jsx          (thin wrap of AiDocumentsDirectory)
│   │   ├── DraftsListPage.jsx
│   │   ├── NewslettersListPage.jsx
│   │   ├── BlogsListPage.jsx
│   │   ├── TemplatesListPage.jsx
│   │   ├── ComposeStartPage.jsx            (template chooser)
│   │   ├── DraftEditorPage.jsx
│   │   ├── NewsletterEditorPage.jsx
│   │   └── BlogEditorPage.jsx
│   ├── components/
│   │   ├── WritingCard.jsx
│   │   ├── WritingHeader.jsx
│   │   ├── TemplateCard.jsx
│   │   └── AskAiButton.jsx
│   └── hooks/
│       ├── useDrafts.js
│       ├── useNewsletters.js
│       ├── useBlogs.js
│       └── useTemplates.js
└── infrastructure/
    └── api/
        ├── drafts.js
        ├── newsletters.js
        ├── blogs.js
        └── templates.js
```

### Editor reuse

All editor pages use `TextAreaReusable` from `src/components/Input/TextArea/TextAreaReusable.js`. Toolbar features: headings, font, bold/italic/underline/strike/blockquote, lists with indent, links, images (uploaded to workspace asset storage), optional video, alignment, clear formatting. Serializes to HTML.

`AskAiButton` calls `writing_agent` endpoint, replaces editor body with returned HTML.

### Compose flow

```
Drafts list page  →  [Compose ▼]  →  ComposeStartPage
                                         ├── Blank Letter
                                         ├── Blank Update
                                         ├── Blank Summary
                                         ├── Blank Newsletter
                                         ├── Blank Blog Post
                                         └── From template...
                                              └── TemplateChooser modal
                                                  → POST /api/content/drafts/ (kind, template)
                                                  → redirect to /writing/draft/<id>
```

---

## 5. Celery — Newsletter cadence pipeline (mirror Reports)

```
Beat schedule (api/settings/base.py):
    'dispatch_scheduled_newsletters_daily': {
        'task': 'content.dispatch_scheduled_newsletters',
        'schedule': crontab(hour=7, minute=0),  # 07:00 UTC daily
    }

components/content/workers/tasks.py:
    @shared_task(name="content.dispatch_scheduled_newsletters", ...)
    def dispatch_scheduled_newsletters(self):
        # Query WorkspacePreference for newsletter_frequency setting
        # Fan out per workspace via SendScheduledNewsletterUseCase
        # Idempotency key: (workspace, range_start, range_end)
        # Each call creates Newsletter(status=ai_drafted)
        # NEVER sends — waits for human review

    @shared_task(name="content.generate_newsletter_draft", ...)
    def generate_newsletter_draft(self, workspace_id, period_start, period_end):
        # Pull workspace metrics (donations, top recipients, upcoming events, recent campaigns)
        # Call writing_agent.draft_newsletter_from_period
        # Create Newsletter row, status=ai_drafted
        # Emit NewsletterDrafted domain event

    @shared_task(name="content.render_draft_pdf", ...)
    def render_draft_pdf(self, kind, id):
        # Gotenberg HTML → PDF
        # Store at MinIO key {workspace}/{kind}/{id}.pdf
        # Stamp pdf_key + pdf_generated_at
```

Cadence config: `WorkspacePreference.settings['newsletter_frequency']` — `none | weekly | biweekly | monthly`. Surfaced in `Workspace → Settings → Automations` UI alongside the existing `financial_report_frequency`.

Autodiscover: `infrastructure/persistence/content/tasks.py` re-exports the task functions so Celery's `autodiscover_tasks()` finds them.

---

## 6. AI Agent — `writing_agent` (ADR 0003)

Location: `components/agents/infrastructure/adapters/langchain/agents/writing_agent.py`.

```python
@register_agent("writing_agent", aliases=("newsletter_agent",))
class WritingAgent:
    profile = {
        'persona_scope': ('admin', 'owner', 'contributor'),
        'role_scope': ('owner', 'admin', 'contributor'),
        'description': 'Drafts newsletters, letters, summaries, blog posts from workspace data.',
    }
```

Tools (`tools/writing_agent.py`):
- `draft_newsletter_from_period(workspace_id, period_start, period_end)` — pulls metrics like Reports does (donations, recipients, events, campaigns), returns intro + sections + CTA HTML.
- `draft_letter(workspace_id, prompt, recipient_name)` — funder thank-you, beneficiary update.
- `summarize_period(workspace_id, period_start, period_end)` — summary doc.
- `generate_blog_post(workspace_id, topic, tone)` — drafts a blog.
- `extract_key_points(document_id)` — for ad-hoc compose from existing docs.

Mapping: add to `components/agents/domain/agent_domain_map.py`. Carve scope: edit `components/agents/infrastructure/adapters/langchain/deep/llm_planner.py` so writing tasks route to `writing_agent` instead of the catch-all.

---

## 7. Pitfalls (don't repeat these)

- **Auto-sending newsletters.** Always lands in `status=ai_drafted` for human review. The only path to `status=sent` is `SendNewsletterUseCase` invoked by a human action endpoint. No backend code path emits `sent` without explicit human trigger.
- **Inline aggregations in views.** Listing newsletters runs `SELECT … WHERE workspace_id=…` against the indexed `Newsletter` table. The metric pull lives in the Celery task. Never run `Sum`/`Count` over workspace metrics inside a view.
- **Adding a new editor library.** No. react-quill stays. Adding Tiptap/Lexical etc. forks the editor surface across the platform.
- **Hardcoding templates on the frontend.** Templates seed on the backend via fixtures. Frontend fetches them.
- **Putting Newsletter back in `landing` context.** Landing isn't a canonical bounded context. Newsletter belongs in `content`.
- **Direct ORM imports in `shared_platform`.** Use `WritingArtifactsPort`, not `from content.models import Newsletter`. (The existing `File` + `FinancialReport` violations stay flagged for separate cleanup.)
- **`window.confirm()` for deletes.** Use `TrashConfirmModal` + `useTransactionTrash` with `entityType`.
- **Forgetting Celery worker restart.** After adding tasks, `docker restart compose-celery_worker-1 compose-celery_beat-1` AND confirm registration in worker logs.
- **Wrapping pages without `Layout`.** Every authenticated page wraps in `<Layout>` from `src/components/Partials/Layout`. `withSection()` does NOT add it. (Frontend CLAUDE.md HARD RULE.)
- **Skipping `/architecture` invocation before backend changes.** This skill encodes the architecture, but baseline tests must run before each chunk: `docker exec compose-web-1 python -m pytest tests/architecture/ -v`.

---

## 8. Key Files

### Backend (reference patterns)
- `components/reports/workers/tasks.py` — Celery Beat + dispatch task pattern to mirror
- `components/reports/application/use_cases/send_scheduled_financial_report_use_case.py` — idempotency + policy pattern
- `components/reports/infrastructure/adapters/gotenberg_financial_report_pdf_renderer.py` — Gotenberg adapter pattern
- `components/shared_platform/infrastructure/services/gotenberg_html_to_pdf_client.py` — shared Gotenberg HTTP client
- `infrastructure/persistence/landing/models.py:117` — current Newsletter model (to be migrated)
- `infrastructure/persistence/workspaces/news/models.py:33` — News (blog) model (stays)
- `components/shared_platform/api/unified_documents_controller.py` — unified-docs reader to extend
- `components/agents/infrastructure/adapters/langchain/agents/` — agent registration pattern
- `components/agents/domain/agent_domain_map.py` — agent mapping table
- `components/agents/infrastructure/adapters/langchain/deep/llm_planner.py` — catch-all planner

### Frontend (reuse)
- `src/components/Input/TextArea/TextAreaReusable.js` — react-quill editor (reuse for all writing surfaces)
- `src/features/documents/presentation/components/AiDocumentsDirectory.jsx` — existing Documents page, wrapped as Library
- `src/components/Partials/Layout` — wrap every authenticated page
- `src/components/Partials/PageHeader` — page header
- `src/components/Tab/TabPills` — tab pills (used in Library)
- `src/components/Button/Button` — primary button (pill default)
- `src/components/EmptyState/EmptyStateBanner` — empty state
- `src/components/Modal/Modal` + `Modal{Header,Body,Footer}` — modals
- `src/components/Trash/TrashConfirmModal` + `src/hooks/useTransactionTrash` — delete via recycle bin

### Plan + tracking
- `/Users/henrywanjala/.claude/plans/graceful-exploring-quiche.md` — full approved plan
- This skill — durable architecture + phased roadmap

---

## 9. Decision Heuristics

**"Where does this code go?"**
- Authoring/publishing artifact (letter / update / summary / memo / newsletter / blog / template) → `components/content`
- Reads of writing artifacts from other contexts → through `WritingArtifactsPort`
- Cadence schedule config → `WorkspacePreference.settings`
- AI draft generation → `writing_agent` tool, called from Celery task

**"Should I add a new Kind to WritingDraft, or a new model?"**
- New model only if the artifact has unique fields/relations that don't fit a TEXT body + title + author shape (e.g., Newsletter has subscribers M2M + sent_at, so it's a sibling model, not a Kind).
- New Kind on WritingDraft is right for: any text-only artifact (letter, update, summary, memo, proposal, brief).

**"Can I extend the existing Documents tabs instead of adding a new page?"**
- The Library tab IS the existing Documents page. Source-type filter (Reports / Uploads / AI Chat / Knowledge / Imports) is unchanged. New tabs (Drafts / Newsletters / Blogs / Templates) get their own pages because they have authoring affordances that don't fit the read-only card-grid pattern of Library.

**"Newsletter generated content arrives — should I send it now?"**
- No. Always lands `status=ai_drafted`. Human reviews + sends.

**"Should I add a new editor for X?"**
- No. `TextAreaReusable` is the editor. If a feature is missing, add it to the react-quill toolbar config, don't fork.

---

## 10. Build Notes (filled in as phases ship)

_To be populated as each phase merges. Capture: bugs hit, deviations from this skill, follow-ups deferred._

### Phase 0 — Foundation (in progress 2026-06-10)
- Plan written: `/Users/henrywanjala/.claude/plans/graceful-exploring-quiche.md`
- Skill written: this file
- Backend worktree created: `writing-surface-be` off `origin/development`
- Frontend worktree created: `worktree-writing-surface-fe` off `origin/development`
- Architecture test baseline: 57 pass / 15 pre-existing fail
- Verified `components/content` exists with News-only contents; new entities/ports/repos go alongside
- Verified naming-rule violations to avoid in new code (entity suffix, port-not-repository-port, etc.)

### Phase 1 — Domain layer (shipped 2026-06-10)
- `components/content/domain/enums.py` — NewsletterStatus, NewsletterCadence, WritingDraftKind, WritingDraftStatus, WritingTemplateKind, WritingArtifactKind
- `components/content/domain/entities/newsletter_entity.py` — frozen dataclass with status validation, ai_drafted_by_agent + period fields
- `components/content/domain/entities/writing_draft_entity.py` — frozen dataclass, Kind discriminator (letter/update/summary/memo)
- `components/content/domain/entities/writing_template_entity.py` — frozen dataclass, global vs workspace-owned validation
- `components/content/domain/events/{newsletter_drafted,newsletter_sent,writing_draft_published,blog_published}_event.py` — frozen kw_only DomainEvent subclasses
- Extended `components/content/domain/errors.py` with NewsletterError + WritingDraftError + WritingTemplateError taxonomies (each extends ContentError + appropriate shared_kernel base)
- ADR 0004 at `docs/adr/0004-writing-surface-and-content-context.md`
- Architecture tests rerun: 57 pass / 15 fail (matches baseline — no regressions)

### Phase 2 — Persistence (shipped 2026-06-10)
- New Django app at `infrastructure/persistence/content/`: `apps.py`, `models.py`, `admin.py`, `migrations/`
- Models: `Subscriber`, `Newsletter`, `WritingTemplate`, `WritingDraft` — each table-prefixed `content_*` to namespace cleanly
- `Newsletter` schema improvements over legacy: explicit `status` enum (default `draft`), `scheduled_for`, `period_start`/`period_end`, `pdf_key` + `pdf_generated_at`, `author` FK, `ai_drafted_by_agent`, `content_html` renamed from legacy `content`, indexed on `(workspace, status)` and `(workspace, -created_at)` and `(workspace, period_start, period_end)`
- `WritingTemplate` CheckConstraint enforces `is_seeded=True` ⇒ `workspace=NULL` (global only)
- Cadence shim in `apps.py.ready()` imports `components.content.workers.tasks` for Celery autodiscover (try/except — Phase 6 fills the tasks)
- INSTALLED_APPS registered: `'infrastructure.persistence.content'` added at `api/settings/base.py:120` between reports and honeypot
- Migration `0001_initial.py` — hand-written initial creating four tables + 9 indexes + 1 check constraint
- Migration `0002_copy_newsletters_from_landing.py` — idempotent `RunPython` data migration keyed by `metadata['legacy_landing_id']`. Copies Subscriber rows (`get_or_create` by email), then Newsletter rows with `sent_at IS NULL → status='draft'` / `sent_at IS NOT NULL → status='sent'` mapping. Rebuilds subscriber M2M. Safe to retry. Legacy `landing.Newsletter` + `landing.Subscriber` tables stay in place as read-only fallback for one release; drop in `0003_drop_landing_newsletter.py` follow-up.

### Phases 3–10 (shipped 2026-06-10 — single long session)
- All backend layers landed in `components/content`, `infrastructure/persistence/content`, plus `writing_agent.py` in agents context.
- Architecture tests after each layer: 57 pass / 15 fail — same as baseline. Zero regressions from any new file.
- Frontend sidebar (`src/config/sidebarSections.ts`) restructured: Documents removed from Teams, Writing added to Workspace with 5 children (Drafts / Newsletters / Blogs / Templates / Library) in BOTH contributor and admin templates.
- 7 frontend routes at `/w/:workspaceId/writing/{library,drafts,newsletters,blogs,templates,compose}` + parent redirect → library.
- 6 placeholder pages: Library wraps the existing `AiDocumentsDirectory` so existing docs render at the new URL; four list pages show EmptyStateBanner with CTAs to Compose / Automations; ComposeStartPage is a stub for Phase 11.

### Phases 11–12 (shipped 2026-06-10)
**API clients** at `src/infrastructure/content/`:
- `writingDraftsApi.ts` — CRUD + publish + exportPdf
- `newslettersApi.ts` — list, get, update, send, generate, exportPdf
- `writingTemplatesApi.ts` — CRUD
- `blogsApi.ts` — wraps existing `/news/<workspace>/` endpoints

**Hooks** at `src/features/writing/presentation/hooks/`:
- `useDrafts.js`, `useNewsletters.js`, `useBlogs.js`, `useTemplates.js` — each provides `{ items, isLoading, error, refresh, create/update/publish/send/etc. }`

**Components** at `src/features/writing/presentation/components/`:
- `WritingCard.jsx` — unified card for any artifact, kind/status chip styling

**Pages** at `src/features/writing/presentation/pages/`:
- List pages (Drafts, Newsletters, Blogs, Templates) now use their hook + WritingCard grid + EmptyStateBanner fallback
- `ComposeStartPage` shows 6 kind cards (4 draft kinds + Newsletter quick-link + Blog quick-link); auto-creates a draft and redirects when `?kind=…` is preselected
- `DraftEditorPage`, `NewsletterEditorPage`, `BlogEditorPage` — full edit surfaces using `TextAreaReusable` (react-quill); Save / Publish (drafts) / Send (newsletters, with explicit confirm) / Export PDF actions
- **Critical UX rule wired**: `NewsletterEditorPage.handleSend` requires `window.confirm()` before calling `newslettersApi.send()` — newsletters are never sent without an explicit human action

**Routes** (3 new editor routes added to the existing 7):
- `/w/:workspaceId/writing/draft/:draftId`
- `/w/:workspaceId/writing/newsletter/:id`
- `/w/:workspaceId/writing/blog/:id`

**Cadence picker** at `src/components/Settings/Tabs/ReportSettingsTab.jsx`:
- Adds a Newsletter Draft Cadence section (Off / Weekly / Biweekly / Monthly) below the existing Report cadence + variant sections
- Saves `newsletter_frequency` to `WorkspacePreference.settings` alongside `financial_report_frequency`
- Section has `id="newsletter"` so list pages can deep-link with `#newsletter`

### Next up — Phase 13: Verification
- `yarn install` in the FE worktree (node_modules not present yet)
- `yarn typecheck`, `yarn test --watchAll=false --testPathPattern=writing`, `yarn lint --no-fix 2>&1 | grep "error "`
- Backend: run `tests/architecture/` + new `components/content/tests/` (write integration tests for: cadence dispatch produces AI_DRAFTED, SendNewsletterUseCase requires human invocation, GenerateNewsletter idempotent on period)
- Playwright MCP smoke per `/octopus-ui-smoke`:
  1. Log in as `founder@zaylan.demo`
  2. Sidebar → Workspace → Writing → Library (verify existing docs render at new URL)
  3. Writing → Drafts → Compose → Blank Letter → write something → Save → confirm row appears
  4. Workspace → Settings → Reports → set Newsletter cadence to Weekly → Save
  5. (Locally) trigger `dispatch_scheduled_newsletters` or `generate_newsletter_draft` via Django shell → confirm row appears in Newsletters
  6. Open AI-drafted newsletter → edit → Send (confirm) → status flips to sent, `sent_at` populated

---

## 11. Verification Commands

Run these before declaring any phase done.

### Backend
```bash
# Architecture tests
docker exec compose-web-1 python -m pytest tests/architecture/ -v

# Content context tests
docker exec compose-web-1 python -m pytest components/content/ -v

# After Celery task changes
docker restart compose-celery_worker-1 compose-celery_beat-1
docker logs compose-celery_worker-1 2>&1 | grep -i 'content\.'
```

### Frontend
```bash
yarn typecheck
yarn test --watchAll=false --testPathPattern=writing
yarn lint --no-fix 2>&1 | grep "error "  # must be zero new
```

### End-to-end smoke (Playwright MCP via `/octopus-ui-smoke`)
1. Log in as `founder@zaylan.demo` (Zaylan demo workspace, seeded by `seed_marketing_demo`)
2. Sidebar → Workspace → Writing → Library — confirm existing docs render
3. Writing → Drafts → Compose → Blank Letter — write, save, confirm in list
4. Workspace → Settings → Automations — set Newsletter cadence to Weekly
5. Trigger `generate_newsletter_draft` via Django admin / shell — confirm row in Newsletters tab
6. Open AI-drafted newsletter, edit, click Send — confirm `sent_at` populated
7. `browser_console_messages` — no new red
8. `browser_take_screenshot` to `~/Desktop/claude-smoke/writing-surface.png`
9. `browser_close`
