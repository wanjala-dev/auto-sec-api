---
name: templates
description: |
  Use BEFORE building, editing, or reasoning about ANY "template" feature anywhere in the platform — newsletters/blogs/letters (WritingTemplate), workflows (WorkflowTemplate), budgets (BudgetTemplate), grant applications + reports (ApplicationTemplate/ReportTemplate), grant snippets, donation forms, or a brand-new template kind. The platform deliberately has ONE Template Kernel (`components/templates/`) + a kind registry; every template system plugs into it for gallery listing, lifecycle (recycle-bin delete/restore), versioning (snapshot-on-publish), and variable/placeholder resolution. This skill exists so contributors NEVER again hand-roll a parallel template system with its own storage, its own delete semantics, or its own gallery UI — which is exactly the fragmentation this kernel was built to end. Invoke alongside `/architecture` before adding a kind or context-crossing change, `/frontend-reuse` before any template gallery/picker UI, and `/celery-tasks` if a kind needs background apply.
---

# Template Kernel

**Mental model.** A *template* is a reusable blueprint a user picks from a **gallery** and **instantiates** (clones/applies) into a concrete entity. Across the platform we have many *kinds* of template (writing, workflow, budget, grant application/report, snippet, donation form), each with a genuinely different **payload** (HTML, a graph, line-item rows, a JSON-Schema). They do NOT share a payload — but they DO share a spine: identity, system-vs-workspace **scoping**, categorization, **versioning**, **lifecycle** (edit / add / delete-to-recycle-bin / restore), and **variable resolution**. The Template Kernel owns that spine; each kind keeps its own payload table and registers with the kernel.

> **Read `docs/plans/TEMPLATE_KERNEL_CONSOLIDATION_2026-06-26.md`** — the roadmap + per-kind migration tracker + phase status. This skill is the durable playbook; that doc is the where-are-we tracker. Keep both current.

---

## 0. The one rule that matters

**Do NOT build a new standalone template system.** When a feature needs templates, **register a kind with the kernel** — you get gallery listing, recycle-bin lifecycle, and (as phases land) versioning + variable resolution for free. Hand-rolling a parallel `*Template` model with its own delete endpoint and its own gallery UI is the exact defect this kernel ends. If the kernel is missing a capability your kind needs, **extend the kernel**, don't fork around it.

This is the templates-specific application of the repo-wide DRY hard rule (CLAUDE.md "Don't Reinvent the Wheel").

---

## 1. Where everything lives

- **Kernel context:** `components/templates/` (thin, registry-driven — mirrors `components/recycle_bin/`).
  - `application/ports/template_source_port.py` — the contract a kind implements to appear in the gallery (`kind()`, `list_templates(workspace_id)` → normalized summaries).
  - `application/providers/template_registry_provider.py` — the kind registry (register + list_by_kind + list_kinds). The composition root.
  - `domain/entities/template_summary.py` — the normalized gallery row (frozen dataclass).
  - `domain/template_kind.py` — the catalogue of known kinds (id, model label, entity_type, scope, default category).
  - `infrastructure/adapters/configurable_template_soft_delete_adapter.py` — ONE generic `SoftDeletePort` impl, parametrized by model label; resolves the model via `apps.get_model()` so the kernel never hard-imports another context's persistence. Reused by every kind.
  - `api/controller.py` + `api/urls.py` — `GET /templates/?kind=` unified gallery read.
- **Per-kind payload tables stay in their owning context's** `infrastructure/persistence/<app>/`. The kind's `TemplateSourcePort` adapter + its registration live in the OWNING context (e.g. budgeting registers its BudgetTemplate source), so the kernel stays decoupled.
- **Lifecycle reuses `components/recycle_bin/`** — register each kind's soft-delete adapter with `recycle_bin_provider.py` (the established composition root that already imports each context's soft-delete providers). Delete → bin → restore → hard-delete is uniform and free.

---

## 2. The kinds that exist (inventory — keep current)

| Kind id | Model | Owning context | Payload | Scope | Versioning |
|---|---|---|---|---|---|
| `writing_template` | WritingTemplate | content | HTML + `{{placeholders}}` | system + workspace | (migrating to snapshot) |
| `workflow_template` | WorkflowTemplate | workflow | graph JSON | system + workspace custom | ✅ snapshot (WorkflowVersion) |
| `budget_template` | BudgetTemplate + Lines | budgeting | line-item rows | system + workspace | (migrating to snapshot) |
| `application_template` | ApplicationTemplate | grants | JSON Schema | system + (workspace×funder) | ✅ explicit version |
| `report_template` | ReportTemplate | grants | JSON Schema | system + (workspace×funder) | ✅ explicit version |
| `grant_snippet` | GrantSnippet | grants | markdown `{{key}}` partial | workspace | — |
| `donation_form_template` | (persisting from `formTemplates.ts`) | donation_forms | tiers + designation JSON | workspace | — |

Not kernel templates (leave alone): `RecurringTransactionTemplate` (a schedule *generator*), `PaymentProvider.config_template` (config schema), notification `verb_templates` (i18n strings).

---

## 3. Constitutional rules (keep the kernel coherent)

1. **One spine, many payloads.** Never flatten heterogeneous payloads into a single polymorphic `Template.payload` JSON table — it destroys FK integrity (line-items, M2M, funder/version FKs) and the grants schema-versioning. Each kind keeps its payload table; the kernel unifies identity/scope/lifecycle/versioning only.
2. **Scoping is `workspace IS NULL` = system, else workspace-owned.** Don't invent a new scoping scheme per kind. (Grants adds a funder dimension on top — that's fine, it's additive.)
3. **Snapshot-on-publish, never mutate-in-place.** Editing a published template must NOT change already-instantiated entities. Capture an immutable version on publish (the WorkflowVersion / grants `version` pattern). In-place mutation that orphans in-flight work is a bug.
4. **Delete goes to the recycle bin.** Every kind registers a `SoftDeletePort` with `recycle_bin_provider`. No hard-delete endpoints, no per-kind delete semantics. `is_deleted=True` + snapshot; restore flips it back; purge cascades at the DB.
5. **Variable resolution is shared** (Phase 3): one resolver, two token classes — saved tokens (resolve from workspace/contact/entity) vs prompt-at-use tokens (HubSpot's distinction). Don't add a 4th bespoke `{{...}}` substitution.
6. **Explicit Architecture.** Ports in `application/ports/`, providers in `application/providers/` (per `.claude/rules/bounded-context-structure.md`). The kernel's generic adapter resolves models via `apps.get_model(label)` — NO `components.<other>.infrastructure` imports and NO hard persistence imports of other contexts' tables. Kind adapters live in the owning context; registration in the composition root.
7. **Gallery read is paginated + `select_related`.** Listing templates is bounded but still goes through the perf rules. It's a read, not a heavy aggregation, so §6a (Celery aggregation) does NOT apply — but don't N+1.
8. **Frontend uses the shared gallery** (Phase 4): `TemplateGallery` / `TemplatePicker` / `TemplatePreviewDrawer` / `TemplateCard` + `useTemplateGallery(kind)` in `src/components/Template/`. Never hand-roll a new gallery/picker (the `/frontend-reuse` hard rule).

---

## 3a. Product principles (Henry, 2026-06-27) — why templates matter

Templates are a **headline, sellable product surface**, not plumbing. They are how a user goes from blank-page paralysis to a working newsletter / blog / monthly report / **automation** in one click, and how they *learn what a workflow even is* by seeing a worked example. The bar: picking and using a template (email, newsletter, blog, workflow, budget) must be **fluid and obvious** — zero pain points. Three principles flow from this:

### A. Storage format is per-kind — never one-size-fits-all
The kernel does NOT mandate a format. Each kind stores what its render + edit needs demand. This is the "one spine, many payloads" rule made concrete:

| Kind | Payload format | Why |
|---|---|---|
| writing (letter/update/memo/**newsletter**/**blog**) | **HTML** body + `{{placeholders}}` (newsletter also keeps a structured **blocks JSON** for the visual composer) | prose is authored + rendered as rich text |
| **workflow** | **JSON graph — a DAG of nodes + edges** (JSONField) | a workflow IS a graph; JSON is the only sane store + it round-trips to the builder canvas. Henry's call: JSON, yes. |
| budget | **relational line-item rows** (not a blob) | must be queryable / summable (planned income/expense, line counts) |
| grant application / report | **JSON Schema** | renders a dynamic form |
| donation form | **JSON config** (tiers, donor-add-on) | structured config the builder pre-fills |

Rule: **HTML for prose, JSON for graphs/configs, rows for line-items.** Don't force a workflow into HTML or a newsletter into rows. The kernel unifies the *spine* (identity, scope, gallery, lifecycle, preview, variables) across these heterogeneous payloads.

### B. Preview is first-class — the user picks by SEEING
A template is chosen visually. Each kind needs a **preview renderer**, delegated from `TemplatePreviewDrawer`:
- HTML kinds (newsletter/blog/letter) → render the (sanitized) HTML.
- **workflow → render the DAG visually** (a mini read-only canvas of nodes+edges) so the user understands the automation before using it — this is what teaches "what a workflow is."
- budget → line-item table with planned income/expense.
- grant → the JSON Schema as a form preview.

The kernel gallery list stays summary-only (cheap, cross-kind); the **preview** is the per-kind rich render. This is the planned next capability (per-kind preview renderers), and it's load-bearing for usability.

### C. Auto-seed starter templates + system workflows on org/teamspace creation
A new workspace/teamspace must **never be a blank slate**. On creation, provision the relevant system templates (workspace=NULL seeds already exist; surface them) AND optionally **auto-instantiate flagship starter automations** that double as living examples. Flagship example (Henry): a **budget-balancing / receipt-accountability workflow** — trigger when a line item lands on a recurring monthly budget; the workflow tracks that entry's lifetime (where did the money go, was it spent, is there a receipt); if no receipt after a window → fire a reminder email. This ties templates ↔ the workflow engine ↔ budget/receipts, and embodies the platform's "every dollar accounted for" north star. Such starters live as **system workflow templates** (seedable, previewable, cloneable) and are the on-ramp that makes automation legible to non-technical nonprofit admins.

### D. Rendering stack — TWO ports, swappable adapters (decided 2026-06-27)
Rendering is infrastructure → it lives behind ports (architecture-manifesto Rule 5: swap the adapter, not the application code). It is **two distinct stages**, so **two ports** — don't conflate them (Gotenberg renders PDF; MJML renders HTML; they are not alternatives to each other):

1. **`TemplateRenderPort`** — `(template_id|markup, data) → HTML`. The HTML-generation stage.
   - Adapter today: **`DjangoTemplateRenderAdapter`** wrapping `render_to_string()` (how reports/receipts already build HTML — `templates/reports/financial_report.html`). Zero new deps.
   - Future adapters (pure additions, no app change): `JinjaRenderAdapter`, **`MjmlEmailRenderAdapter`** (responsive-email HTML). **MJML belongs HERE**, as a render-port adapter for the email/newsletter kinds — not as a Gotenberg alternative.
   - This port ALSO carries the shared variable/placeholder resolver (§3 rule 5) + powers preview (§3a.B). One port, used by every kind's render + the preview drawer.

2. **`HtmlToPdfPort`** — `HTML → PDF bytes`. The PDF stage (only kinds that need a PDF).
   - Adapter today: **`GotenbergHtmlToPdfAdapter`** wrapping the shared `GotenbergHtmlToPdfClient` (Chromium). The single PDF renderer for reports/receipts/writing exports. **ReportLab is dead — do not reintroduce.**
   - Future adapters: `WeasyPrintHtmlToPdfAdapter`, a cloud-PDF API.

**One path, three outputs:** `data → TemplateRenderPort → HTML → (HtmlToPdfPort → PDF | email send | preview)`. Preview = stop after the render port.

**Today vs target (validated):** reports ALREADY prove the pattern — `components/reports/application/ports/financial_report_pdf_renderer_port.py` + the Gotenberg adapter. BUT it's **report-specific**, and receipts/writing instantiate `GotenbergHtmlToPdfClient()` directly (no shared port). **Target: hoist both generic ports into the Template Kernel (or `shared_platform/application/ports/`), wire Gotenberg + Django-templates as the first adapters, and migrate reports/receipts/writing onto them.** Then MJML / WeasyPrint are pure adapter additions — exactly the swap-the-adapter design. (Phase 3 + 4.2 build these two ports; that's the "shared renderer," done correctly as ports not a util.)

**MJML = deferred, optional** — only adopt the `MjmlEmailRenderAdapter` IF customers hit broken-email-in-Outlook; it adds a JS/transpile dep. The port makes it a drop-in when/if needed.

## 4. Adding a new template kind (the 5 steps)

1. **Payload table** in the owning context's `infrastructure/persistence/<app>/`, adopting the `TemplateBase` mixin (scope, category, status, version, audit, `is_deleted`) — Phase 2+.
2. **`TemplateSourcePort` adapter** in the owning context's `infrastructure/adapters/` returning normalized `TemplateSummary` rows; register it with `template_registry_provider`.
3. **Soft-delete registration**: instantiate `ConfigurableTemplateSoftDeleteAdapter(model_label="<app>.<Model>", entity_type="<kind_id>", name_field="name")` and register it in `recycle_bin_provider.py`.
4. **Instantiate path** (`clone`/`apply`) — keep the domain-specific apply in the owning context; expose it via the kind's controller. Snapshot-on-publish.
5. **Frontend**: render via the shared `TemplateGallery` with `kind="<kind_id>"`. Add the kind to the inventory table in §2 + the consolidation doc.

---

## 5. Per-PR checklist
1. Touching templates? → you registered a kind, you did NOT fork a new system.
2. New kind? → payload table (TemplateBase), TemplateSourcePort adapter + registration, recycle-bin soft-delete registration, snapshot-on-publish, shared frontend gallery, inventory updated.
3. Delete path? → goes to recycle bin via the registry; restore + purge tested.
4. Versioning? → snapshot-on-publish; never mutate a published template in place.
5. Variables/placeholders? → shared resolver (Phase 3), not a new substitution.
6. UI? → `/frontend-reuse`; shared `TemplateGallery`/`TemplatePicker`, not a new one.
7. Run `tests/architecture` + the templates + recycle_bin + touched-context tests + `makemigrations --check`; respect the EC2 gate before deploy.
