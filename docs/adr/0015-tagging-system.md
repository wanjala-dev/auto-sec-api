# ADR 0015 — Tagging system: one workspace-scoped Tag vocabulary + explicit per-context join tables (findings first), no GenericForeignKey

Status: Proposed (2026-08-03) — **design only, no build**

Relates to: **ADR 0004** (the CNAPP Finding SSOT + Asset-graph spine — findings are the first
taggable, and tag-filtered finding reads compose with that spine), **ADR 0013** (contextual-risk
scoring / `list_ranked_findings` — the ranked read a `tag_ids` filter must fold into, not fork),
**ADR 0009** (compliance-lens evidence — scanner-derived `compliance` tags vs operator-asserted
control labels), **ADR 0011** (sample-data mode — sample findings should ship with sample tags),
the **planned saved-views surface** (the Tom + William HUD convergence — a saved view filters by
tag), and the component-decoupling rules in `.claude/skills/architecture/SKILL.md` (C4 —
value-identity correlation, not cross-context FKs into other contexts' internals) +
`.claude/rules/architecture-manifesto.md` (Rule 3 — cross-context communication via ports / shared
kernel, never each other's infrastructure).

## Context

Henry: *"Add a tagging system — pretty sure wanjala-api had a concept of tags; they can tag findings
etc."* Operators keep asking for the same capability three different ways:

- **Tom** (operator-founder, builder ICP): *the single-pane cockpit needs ownership* — "who owns
  this finding, which service, which team." Ownership is a tag.
- **William** (3rd interview, ex-Clio SIEM): *"let me accept the risk knowingly"* and *"the few
  that actually matter"* — both need a way to **label a subset** and then **filter to it**
  (risk-accepted, triaged, this-sprint, owner:me). His convergence with Tom on a persona-templated
  HUD that answers *"what do I need to know today"* is only as good as the **saved views** it sorts
  on — and a saved view is a **stored filter**, of which a tag filter is the most natural primitive.
- **Andrea** (compliance lens, ADR 0009): control labelling — "this finding maps to CC6.1."

Tagging is the small, cross-cutting primitive that all three lean on. It is also the primitive that,
done wrong, silently rots a multi-tenant security product (a tag applied in tenant A leaking its
vocabulary into tenant B; a `GenericForeignKey` quietly coupling every context to a central table;
a per-context copy-paste of the same Tag model six times). This ADR designs it once so we never
design it again.

### What Auto-Sec INHERITED from the fork (grounding — grep, not guess)

The fork **kept a thin, fork-drifted `Tag` model** and stripped every per-context tag model that
lived in a removed nonprofit context:

**Kept (fork-drift — do not build on as-is):**

- `infrastructure/persistence/workspaces/models.py:51` — `class Tag(ObjectTracking)`: **`name`
  only**. It extends `ObjectTracking` (auto `created_at`/`updated_at`, **integer PK**), has **no
  `workspace` FK**, **no soft-delete**, **no colour / slug / category**. It is a **single global tag
  pool** shared across all tenants.
- Applied via plain M2M on three surviving models:
  `Workspace.tags` (`workspaces/models.py:212`), `WorkspaceMembership.tags`
  (`:363` — commented "Workspace-scoped CRM tags … so a tag applied in one workspace never leaks
  into another", but **the scoping is a lie**: the `Tag` rows themselves are global, only the M2M
  edge is per-membership, so the tag *vocabulary* is shared tenant-wide), and a grant model
  (`:516`). `create_tags()` helpers (`:244`, `:518`) auto-attach.
- `components/workspace/api/controller.py:433` `WorkspaceTagList` → `workspace_service.get_all_tags()`
  → `GET /workspace/tags/` **lists every tag globally** (no workspace scope). DTOs in
  `components/workspace/api/resources/tag_resource.py` (`id: int`, `name`).
- **Free-form JSONField tags** on four grant-adjacent models (`workspaces/models.py:1183,1246,1398,1463`
  — `tags = models.JSONField(default=list)`): opaque string lists, no vocabulary, no colour, not
  queryable by a real join.

**Stripped (lived in removed contexts — gone):** `contacts.ContactTag`, `social.Tag`, `project.Tag`,
`sponsorship.recipients.Tag`, `sponsorship.campaign` tags, `news` tags. **No reusable tag primitive
remains** — the surviving `workspaces.Tag` is the wrong shape for a security tool and the rest went
with their contexts.

### The wanjala-api reference model (how the source did it)

wanjala-api (`/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0`) had **6+ separate per-context
`Tag` models**, each attached to its entity by a **plain M2M join — never a `GenericForeignKey`.**
The best-designed of them is the template to steal from:

`infrastructure/persistence/contacts/models.py::ContactTag` — workspace-scoped (`workspace` FK),
`name` + `color`, `StandardMetadata` (UUID PK + soft-delete via `ActiveManager`), unique
`(workspace, name)` **conditioned on `is_deleted=False`**, indexed `(workspace, is_deleted)`. Its
docstring is the crux: it justifies being a **new** model *"(not a reuse of the 6+ existing per-context
Tag models) because every existing tag attaches to a different object … none attach to a person."*

The lesson is double-edged: wanjala **correctly chose per-entity joins over a GFK** (fast, referential,
clean), but **paid for it in duplication** — six Tag models, six vocabularies, no shared namespace. It
tagged with an M2M-to-a-local-`Tag`; it never unified the *vocabulary*. Auto-Sec should keep the
per-entity-join instinct and **fix the duplication** by sharing ONE Tag vocabulary across the
per-context joins (improve-don't-replicate).

### Where a tag attaches on a Finding (the first taggable)

- `infrastructure/persistence/findings/models.py::Finding` — the SSOT row (workspace FK, `source`,
  `fingerprint`, `severity`, `status`, `compliance` JSONField, `attributes` JSONField). A
  `FindingTag` join FKs this.
- `components/findings/domain/entities/finding_entity.py::FindingEntity` — frozen dataclass; a
  `tags: tuple[TagRef, ...]` read-only projection is the clean carrier.
- `components/findings/application/ports/finding_store_port.py::list_ranked_findings` — the
  contextual-risk-ranked CQRS read (ADR 0013). A `tag_ids` filter folds in **here**, as one more
  AND-ed, indexed predicate — never a second code path.
- **`FindingStatusView` (`POST /findings/workspaces/<ws>/<finding_id>/status/`) is the exact shape a
  tag/untag endpoint mirrors:** thin `APIView`, `is_workspace_member` gate, `{action: …}` body,
  provider-built use case, `{success, data}` envelope, `logger.info` audit line. Copy it.

## Best-practice research (grounded, not assumed)

**GFK vs explicit join — the Django performance + integrity verdict.** A `GenericForeignKey` (the
`django-taggit` default: `content_type` + `object_id`) buys flexibility (one `Tag` attaches to any
model) at the cost of **an extra join through the content-type table on every resolve, no database
referential integrity, and worse query plans** — the well-known "avoid GenericForeignKey" critique.
An explicit join with a **real FK** gives *"the speed and referential guarantees of a real
ForeignKey"* and is the recommended shape when you tag *a few known model types* rather than *anything
in the project*.[^gfk][^taggit][^lukeplant] A CNAPP tags a **small, known set** (findings now; assets,
tasks later) and needs **fast tag-filtered finding queries at scale** — precisely the case the
literature says picks the explicit join.

**How the CNAPP incumbents productize tags.** Wiz builds a **Service Catalog**: cloud assets + issues
+ ownership grouped around services, *"with reliable tagging and clear ownership as the basics"*, and
routes each finding to the owning team by **tying ownership to the asset tag so a re-scored finding
always reaches the same accountable team.** Orca scores every alert by exploitability × asset
criticality × exposure × data sensitivity — **asset criticality is a tag/label overlay** on the
asset.[^wiz][^orca] The productized pattern is: **ownership + criticality + triage-state as
tags/labels, feeding routing, prioritization, and saved views.**

**Namespaced `key:value` labels.** GitHub-style flat labels (colour-grouped by theme, write-access
gated) are the low-friction floor; Kubernetes-style `key:value` labels are the structured ceiling.[^gh][^k8s]
For a security tool the useful middle is **free-form tags with a reserved set of `namespace:value`
system namespaces** (`owner:`, `env:`, `team:`, `compliance:`, `risk:`) — free enough for operators,
structured enough for automation and saved views to key off.

## Decision

### D1 — Tag by an explicit per-context join FK-ing ONE shared Tag vocabulary. NOT a GenericForeignKey. NOT a per-context Tag model.

The taggable association for findings is an explicit join table **`FindingTag`** with a **real FK to
`Finding`** and a **real FK to a shared `Tag`**. We reject the GFK (worse query plans, no referential
integrity, cross-context content-type coupling) and we reject wanjala's per-context-`Tag` duplication
(six vocabularies). The synthesis — **one vocabulary, many explicit joins** — keeps the fast indexed
join *and* is DRY. Each future taggable (assets, tasks) adds its own `<Entity>Tag` join to the **same**
`Tag`; no GFK ever enters the codebase.

*Why this satisfies Explicit Architecture:* a GFK from a central `tagging` app into every taggable
table is exactly the reverse-coupling C4 forbids (it makes the tag store *know* every context's
internals via content-types). Per-context joins keep each taggable owning its own association, FK-ing
only the **shared vocabulary** — the same "correlate by shared value-identity, not by FK into another
context's guts" discipline the Finding↔Asset `asset_urn` link already uses (ADR 0004 D4).

### D2 — A new `tagging` shared context owns the Tag vocabulary. The inherited `workspaces.Tag` is deprecated fork-drift.

Create `components/tagging/` — a small, shared, workspace-scoped **vocabulary** context (like a
shared-kernel primitive, but with its own CRUD surface, so it gets a real bounded-context home rather
than bloating `shared_kernel`). It owns the `Tag` entity, `TagStorePort`, and tag CRUD. It depends on
nothing but `workspace` identity + `shared_kernel`.

The inherited `workspaces.Tag` (global, integer-PK, workspace-less) is **not** the canonical Tag — it
is fork-drift that would leak tag vocabularies across tenants. The new `tagging.Tag` supersedes it.
Migration of the three surviving M2Ms (`Workspace`/`WorkspaceMembership`/grant) is **out of scope
here** (those are low-value nonprofit-residue surfaces); they keep the legacy `Tag` until a later
boy-scout pass retires it. New code uses `tagging.Tag` exclusively.

### D3 — The `Tag` model: workspace-scoped, UUID PK, slug-unique, coloured, namespaced, system-vs-user, soft-deleted.

`infrastructure/persistence/tagging/models.py::Tag` (fields, in the house order PK → FK → data →
metadata):

| Field | Type | Purpose |
|---|---|---|
| `id` | `UUIDField` PK | UUID like every autosec model (not the legacy int). |
| `workspace` | FK → `Workspace` `CASCADE` | **Hard tenant scope** — the fix for the inherited leak. |
| `name` | `CharField(64)` | Display label ("Payments team", "Risk accepted"). |
| `slug` | `SlugField` | Normalized key; the **per-workspace unique** identity. |
| `namespace` | `CharField(32)`, blank | Optional reserved key (`owner`, `env`, `team`, `compliance`, `risk`). Empty = free-form flat tag. |
| `color` | `CharField(16)`, blank | HUD chip colour (hex or a HUD palette token). |
| `description` | `TextField`, blank | What the tag means (hover / admin). |
| `kind` | `CharField(16)` choices `user` \| `system` | `system` tags are managed by Auto-Sec (reserved, not user-deletable). |
| `is_reserved` | `BooleanField` | Reserved names (`risk:accepted`) can't be re-created/renamed by users. |
| created/updated/soft-delete | `StandardMetadata`-style | Soft-delete + `.active` manager (never hard-delete a tag that's in use). |

Constraints/indexes: `UniqueConstraint(workspace, slug, condition=is_deleted=False)`;
`Index(workspace, is_deleted)`; `Index(workspace, namespace)`. Slug is derived from `namespace:name`
so `owner:alice` and a flat `alice` are distinct.

### D4 — Free-form tags, with a reserved set of `namespace:value` system namespaces.

Tags are free-form by default (operators type them). A small **reserved namespace set** —
`owner:`, `team:`, `env:`, `compliance:`, `risk:` — is recognised by the system for automation, saved
views, and routing. Reserved-namespace tags may be **system-managed** (see D6/D7). Colours group by
namespace by default (owner=blue, risk=red, compliance=violet…). This gives operators GitHub-label
ergonomics and gives automation Kubernetes-label structure without forcing either.

### D5 — Domain + ports + API (mirror the finding-status seam).

- **Domain (`components/tagging/domain/`):** `TagEntity` (frozen dataclass — `id`, `workspace_id`,
  `name`, `slug`, `namespace`, `color`, `kind`, invariants in `__post_init__`: non-empty name, slug
  format, reserved-name guard). A `TagRef` value object (`id`, `slug`, `name`, `color`) is the light
  read projection carried on taggable entities (e.g. `FindingEntity.tags`).
- **Ports (`components/tagging/application/ports/`):** `TagStorePort` — `create`, `rename`,
  `set_color`, `soft_delete`, `find_by_slug`, `list_for_workspace(namespace=None)`,
  `get_or_create(workspace, name, namespace)` (the tag-a-finding fast path), `bulk_ref(ids)`.
- **Tagging CRUD API (`components/tagging/api/`):** workspace-scoped, member-gated —
  `GET/POST /tagging/workspaces/<ws>/tags/`, `PATCH/DELETE …/tags/<tag_id>/`. Thin controllers, DTOs
  in `api/resources/`, provider-built use cases. **Deletes are soft** (a tag in use is retired, its
  joins detached by a background task, never a hard cascade that silently un-tags history).
- **Tag/untag a finding (owned by the `findings` context — the join lives with the entity it tags):**
  `POST /findings/workspaces/<ws>/<finding_id>/tags/` `{add: [slug|id], remove: [slug|id]}` and
  `DELETE …/tags/<tag_id>/`. **Modeled 1:1 on `FindingStatusView`** — `is_workspace_member` gate,
  `{success,data}` envelope, `logger.info tag_applied workspace_id=… finding_id=… tag_slug=…
  actor_id=…` audit. A `TagFindingUseCase` (in `components/findings/application/use_cases/`) resolves
  slugs via `TagStorePort.get_or_create` (auto-create free-form tags on first use), writes
  `FindingTag` rows, and — like every AI/operator action — is auditable.
- **Where `FindingTag` lives:** `infrastructure/persistence/findings/` (co-located with `Finding`,
  FK → `Finding` + FK → `tagging.Tag`), owned/written by the **findings** context. Cross-context
  read of the vocabulary is through `TagStorePort` (no findings→tagging *infrastructure* import). A
  persistence-layer FK to `tagging.Tag` is fine (single-DB; models FK across apps normally — the
  boundary rule governs *component* imports, not ORM FKs in the outermost ring).

### D6 — Filtering findings by tag folds into the existing ranked read (one path, indexed join).

`FindingStorePort.list_ranked_findings` (and `list_findings` / `count_findings`) gain an optional
`tag_ids: tuple[UUID, ...] | None` (+ `tag_match: "any" | "all"`). The `DjangoFindingRepository`
resolves it as an **indexed JOIN on `FindingTag`** inside the *same* query that already applies
severity/status/source and the `FindingRisk` risk ordering — **not** a second code path, and **not**
a resolve-ids-then-`id__in` round trip. `FindingTag` carries `Index(workspace, tag)` and
`Index(finding)` so `filter findings by tag(s)` stays O(matched) at scale. This is the substrate the
BRIEF severity tabs, finding filters, and saved views all read.

### D7 — Composition with risk-acceptance, compliance, saved views, automation.

- **Risk-accept-with-reason (William) — status is the SSOT; a reserved tag is a derived label, not the
  truth.** "Accepted risk" is **already** a finding *lifecycle* state: `ChangeFindingStatusUseCase`'s
  `suppress` → `SUPPRESSED`. We do **not** fork that into a free user-editable `risk-accepted` tag
  (that would give a finding two conflicting sources of truth — a shortcut). Instead: **extend the
  suppress action to capture a `reason`** (the accept-with-reason William asked for), and expose a
  **system-managed, read-only reserved tag `risk:accepted`** that the system auto-syncs to suppressed
  findings so the same finding shows up in tag-filtered views and saved views. Reason lives with the
  lifecycle action (auditable); the tag is a projection of status, never user-set. *(Open question Q2
  refines whether the reason lives on the status command or the FindingTag.)*
- **Compliance (ADR 0009) — scanner-derived stays authoritative; a `compliance:` namespace is an
  operator overlay.** `Finding.compliance` (`{framework: [controls]}`, scanner-populated) remains the
  SSOT the compliance summary rolls up. A reserved **`compliance:` tag namespace** lets operators
  *assert* additional control mappings the scanner didn't emit; the compliance summary may **union**
  these, clearly labelled "operator-asserted" vs "scanner-derived" (provenance is the product —
  Andrea). No duplication of the scanner field.
- **Saved views (Tom + William HUD convergence).** A saved view is a stored filter set; a **tag
  filter is its highest-value primitive** ("owner:me + risk:red", "team:payments + status:open").
  Saved views compose over D6's `tag_ids` filter — this ADR ships the substrate; the saved-views ADR
  consumes it.
- **Workflow automation.** The inherited `workflow` engine already has an **"Add Tag" action**. A
  tag-based rule (trigger: finding observed → condition → **Add Tag** `owner:payments`) routes
  findings to owners exactly as Wiz does. `FindingTag.source` = `user | agent | rule` records
  provenance so an auto-applied tag is distinguishable from an operator's.
- **Finding action row (#78).** Gets a **Tag** action alongside Resolve/Suppress/Reopen, calling the
  D5 tag/untag endpoint — inline, without leaving the callout.

### D8 — `FindingTag` join shape.

`infrastructure/persistence/findings/models.py::FindingTag`: `id` UUID PK; `workspace` FK
(denormalized for the scoped indexed filter); `finding` FK `CASCADE`; `tag` FK → `tagging.Tag`
`CASCADE`; `applied_by` (user id, nullable — null = system/rule); `source`
(`user | agent | rule | system`); `reason` (blank — used by the derived `risk:accepted` sync and by
automation); `applied_at`. `UniqueConstraint(finding, tag)`; `Index(workspace, tag)`;
`Index(finding)`.

## Consequences

**Positive**
- One canonical, tenant-scoped tag vocabulary — the inherited cross-tenant leak is designed out.
- Fast, referential, index-backed tag-filtered finding queries; no GFK content-type indirection.
- DRY: findings, assets, tasks share ONE `Tag` + `TagStorePort`; each adds a thin join, not a Tag
  model — fixing wanjala's six-vocabulary duplication.
- Clean boundaries: tagging owns the vocabulary behind a port; each taggable owns its own join; no
  cross-context infrastructure import; no GFK reverse-coupling.
- Composes with (doesn't fork) the ranked read, the lifecycle SSOT, the compliance field, saved
  views, and the workflow engine.

**Negative / costs**
- A new bounded context (`tagging`) — small, but real scaffolding (context + persistence app +
  migration).
- Two legacy tag surfaces linger (global `workspaces.Tag` M2Ms; grant JSONField tags) until a
  boy-scout retirement — dual-read risk if not clearly fenced ("new code uses `tagging.Tag`").
- Each new taggable is a (small) explicit join + migration — the deliberate cost of avoiding the GFK.

## Phased plan

- **P1 — Vocabulary + findings taggable + filter.** `tagging` context: `Tag` model/entity/port/CRUD
  API (per-workspace, member-gated, soft-delete). `FindingTag` join. `TagFindingUseCase` +
  tag/untag-a-finding endpoint (mirror `FindingStatusView`). `tag_ids`/`tag_match` on
  `list_ranked_findings` (indexed JOIN). Query-count regression test (constant w.r.t. rows — perf
  rule §1). Reserved-namespace recognition. Frontend: Tag action on the #78 row + tag chips on the
  finding callout + a tag filter on the BRIEF/list.
- **P2 — Saved views + risk-accept reason + compliance overlay.** `reason` on the suppress action;
  system-managed `risk:accepted` derived tag sync; `compliance:` operator-asserted namespace unioned
  (labelled) into the compliance summary; saved views consume the tag filter; sample-data mode (ADR
  0011) ships sample tags.
- **P3 — Assets + tasks taggable + automation.** `AssetTag` (cloud_graph) + `TaskTag` (board) joins
  on the same `Tag`; wire the workflow "Add Tag" action to findings/assets with `source=rule`;
  ownership-routing (Wiz Service-Catalog pattern) via `owner:`/`team:` tags. Retire the legacy
  `workspaces.Tag` M2Ms + grant JSONField tags onto the canonical vocabulary (boy-scout).

## Open questions

1. **`tagging` as a full bounded context vs a `shared_kernel` primitive.** A full context gives it a
   CRUD API home and room to grow (tag groups, tag policies); `shared_kernel` is lighter but has no
   API surface. Recommendation leans **full context** (it has its own endpoints + lifecycle). Confirm.
2. **Where the risk-acceptance `reason` lives.** On `ChangeFindingStatusCommand` (reason-as-lifecycle,
   cleanest — status is the SSOT) vs on `FindingTag.reason` of the derived `risk:accepted` tag
   (reason-as-tag-metadata, reuses the join field). D7 recommends the former; the derived tag stays
   read-only. Confirm before P2.
3. **Free-form tag creation — open, or admin-curated vocabulary?** Auto-create-on-first-use
   (`get_or_create`, low friction, Tom-friendly) risks vocabulary sprawl; an admin-curated allow-list
   (William's "controlled") is tidier but heavier. Recommendation: **free-form for `user` tags,
   reserved/curated for system namespaces**, with a later per-workspace toggle to lock the vocabulary.
   Is the open default right for the demo/GTM stage?

[^gfk]: MicroPyramid, *Generic Many-to-Many Relationships in Django* — the GFK content-type extra-join cost. https://micropyramid.com/blog/django-generic-many-to-many-field/
[^taggit]: *Customizing taggit* (django-taggit docs) — custom through-model with a concrete FK for "the speed and referential guarantees of a real ForeignKey." https://django-taggit.readthedocs.io/en/latest/custom_tagging.html
[^lukeplant]: Luke Plant, *Avoid Django's GenericForeignKey* — no DB referential integrity, worse query plans. https://lukeplant.me.uk/blog/posts/avoid-django-genericforeignkey/
[^wiz]: Wiz, *Reducing Risk through Service Ownership* — tagging + ownership as the basics; ownership tied to the asset tag for finding routing. https://www.wiz.io/blog/reducing-risk-through-service-ownership
[^orca]: Orca Security, *Risk-Based Vulnerability Management* — asset-criticality label feeding prioritization. https://orca.security/resources/blog/risk-based-vulnerability-management/
[^gh]: GitHub Docs / *Github Labels Guide* — colour-grouped, write-gated flat labels feeding automation. https://docs.github.com/en/issues
[^k8s]: Tigera/Calico, *Label standard and best practices for Kubernetes security* — `key:value` namespaced labels for security. https://www.tigera.io/blog/label-standard-and-best-practices-for-kubernetes-security/
