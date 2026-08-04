# ADR 0015 — Tagging system: one workspace-scoped Tag vocabulary + explicit per-context join tables (findings first), no GenericForeignKey

Status: **Accepted** (2026-08-03, pending merge of PR #233) — decisions locked, implementation-grade. Design only; the build follows this spec.

Relates to: **ADR 0004** (the CNAPP Finding SSOT + Asset-graph spine — findings are the first
taggable, and tag-filtered finding reads compose with that spine), **ADR 0013** (contextual-risk
scoring / `list_ranked_findings` — the ranked read the tag filter folds into, not forks),
**ADR 0009** (compliance-lens evidence — scanner-derived `compliance` stays authoritative; a
`compliance:` tag namespace is an operator overlay), **ADR 0011** (sample-data mode — sample
findings ship with sample tags), the **planned saved-views surface** (the Tom + William HUD
convergence — a saved view filters by tag), and the component-decoupling rules in
`.claude/skills/architecture/SKILL.md` (C4 — value-identity correlation, not cross-context FKs
into other contexts' internals) + `.claude/rules/architecture-manifesto.md` (Rule 3 —
cross-context communication via ports / shared kernel, never each other's infrastructure).

Legacy-surface cleanup note: retirement of the inherited **global `workspaces.Tag`** surface
(the tenant-leaking fork-drift analysed below) is **tracked separately in #83**. P1 of this ADR
must NOT build on, extend, or migrate that surface — it builds the canonical vocabulary beside it
and fences it off ("new code uses `tagging.Tag` exclusively").

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
- The `workflow` engine's existing **`add_tag` / `remove_tag` actions mutate the legacy membership
  M2M** (`components/workflow/tests/integration/test_node_actions_phase2.py`) — i.e. today's
  workflow tagging rides the fork-drift surface, not a canonical vocabulary. Rewiring it is P3.

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
tagged with an M2M-to-a-local-`Tag`; it never unified the *vocabulary*. Auto-Sec keeps the
per-entity-join instinct and **fixes the duplication** by sharing ONE Tag vocabulary across the
per-context joins (improve-don't-replicate).

(Note: autosec has no shared `StandardMetadata` base — the local idiom, e.g.
`infrastructure/persistence/security_templates/models.py`, is explicit `is_deleted` +
`created_at`/`updated_at` fields + an `(workspace, is_deleted)` index. The Tag model below follows
the local idiom, not the wanjala base class.)

### Where a tag attaches on a Finding (the first taggable — verified against the live code)

- `infrastructure/persistence/findings/models.py::Finding` — the SSOT row (UUID PK, `workspace` FK,
  `source`, `fingerprint`, `severity`, `status`, `compliance` JSONField, `attributes` JSONField;
  indexes `(workspace, severity, -last_seen_at)`, `(workspace, status, -last_seen_at)`,
  `(workspace, asset_urn)`). No soft-delete — findings carry a *lifecycle* (`status`), never a
  delete. The `FindingTag` join FKs this.
- `components/findings/domain/entities/finding_entity.py::FindingEntity` — frozen dataclass; gains
  `tags: tuple[TagRef, ...] = ()` as the read-only projection.
- `components/findings/application/ports/finding_store_port.py` — `list_findings` /
  `list_ranked_findings` / `count_findings` share the filter kwargs
  (`severity`, `status`, `source`, `asset_urn`); the tag filter is added to all three (D7).
- **`FindingStatusView` (`POST /findings/workspaces/<ws>/<finding_id>/status/`) is the exact shape
  the tag/untag endpoint mirrors** (verified `components/findings/api/controller.py:62`): thin
  `APIView`, `is_workspace_member` gate (boundary-clean copy in
  `components/findings/infrastructure/services/workspace_access.py`), request DTO →
  provider-built use case → `{success, data}` envelope, domain errors → 404/400.
- `ChangeFindingStatusCommand` (`workspace_id`, `finding_id`, `action`, `at`, `actor_id`) is the
  command the risk-acceptance `reason`/`expires_at` extension lands on (D9).

## Research grounding (claim → source)

Every locked decision below is grounded in one or more of these. Full URLs in the footnotes.

| # | Claim | Source |
|---|---|---|
| R1 | Django GFKs cost an extra content-type join, have **no DB referential integrity**, and produce worse query plans; explicit through-models with a concrete FK give "the speed and referential guarantees of a real ForeignKey" | Luke Plant, *Avoid Django's GenericForeignKey*[^lukeplant]; django-taggit *Customizing taggit* docs[^taggit]; Django contenttypes docs[^contenttypes] |
| R2 | GFK columns are **not indexed by default** — a silent seq-scan trap at scale | Tristan Kernan, *Django: Index Your Generic Foreign Keys*[^tmk] |
| R3 | Junction-table best practice: composite unique/PK on the two FKs + an index serving the **other** direction; a composite index only serves prefix-ordered lookups | PostgreSQL index/prefix behaviour + M2M design guides[^junction] |
| R4 | AWS: **50 user tags/resource**, key ≤128 chars, value ≤256 chars, charset letters/numbers/spaces `_ . : / = + - @`, `aws:` prefix reserved for the platform | AWS Tagging service quotas[^aws] |
| R5 | Datadog: tags ≤**200 chars**, `key:value` form, **normalized to lowercase**, start with a letter; unified service tagging standardizes `env` / `service` / `version` keys | Datadog *Getting Started with Tags*[^datadog] |
| R6 | Kubernetes: label name ≤**63 chars**, alphanumeric ends, `- _ .` inside; **`kubernetes.io/` and `k8s.io/` prefixes reserved for the platform** — the canonical "system namespace is platform-writable only" precedent | Kubernetes labels docs[^k8s] |
| R7 | GitLab **scoped labels** `key::value`: same-key labels are mutually exclusive; applying a second `workflow::` label replaces the first — the productized namespace-semantics precedent | GitLab labels docs[^gitlab] |
| R8 | GitHub labels: name < **50 chars**, ≤ **100 labels per issue**, **write access** may create/edit/delete; **rename propagates** to every labelled issue; filter syntax = space-separated qualifiers **AND**, comma **OR** within `label:`, `-label:` excludes | GitHub *Managing labels* + *Filtering issues*, label-OR changelog[^gh] |
| R9 | Jira labels (negative example): unmanaged, **case-sensitive** strings — `macOS` vs `macos` become separate labels, bulk cleanup is a years-old open pain — the argument for a managed Tag entity + normalized slug | Atlassian JRACLOUD-24907 / JRACLOUD-41181[^jira] |
| R10 | Snyk ignore = **reason (categorised: not vulnerable / won't fix / temporary) + hard `expires` timestamp**; after expiry the finding **reappears as if never ignored**; an org setting restricts ignoring to **admins only** | Snyk ignore docs + `.snyk` policy structure[^snyk] |
| R11 | DefectDojo risk acceptance carries an **expiration date; on expiry the findings are set Active again** — the security-native auto-reopen semantics | DefectDojo *Risk Acceptances*[^defectdojo] |
| R12 | AWS **tag policies** (Organizations): a curated tag schema (allowed keys/values, casing) centrally defined and optionally **enforced** — the governance-lock precedent | AWS Organizations tag policies[^awspolicy] |
| R13 | Wiz productizes **ownership as asset/service tags** ("reliable tagging and clear ownership as the basics") routing findings to the owning team; Orca overlays **asset criticality** on prioritization | Wiz Service Catalog / ownership blog; Orca risk-based VM[^wiz][^orca] |
| R14 | Sentry tags: key ≤32 chars, value ≤200, key charset letters/digits `_ . : -` — a second security-adjacent charset/limit datapoint | Sentry tags docs[^sentry] |
| R15 | Tag **merge** is a real, persistent user demand in mature tag systems (years of Evernote feature-request threads) but not table stakes — P2, not P1 | Evernote forums[^evernote] |

## Decisions (LOCKED)

### D1 — Association model: explicit per-context join FK-ing ONE shared Tag vocabulary. NOT a GenericForeignKey. NOT per-context Tag models. **[locked — confirmed by R1–R3]**

The taggable association for findings is an explicit join table **`FindingTag`** with a real FK to
`Finding` and a real FK to a shared `Tag`. The research **confirms** the draft: the GFK alternative
(django-taggit's default) pays a content-type join on every resolve, has no DB referential
integrity, and isn't even indexed by default (R1, R2) — for a product whose hottest list read will
be "findings having tag X, risk-ranked", that is the wrong substrate. taggit's own docs point
heavy users at a concrete-FK through-model (R1). A CNAPP tags a **small, known set** of entity
types (findings now; assets, tasks at P3) — exactly the case the literature says picks the
explicit join. Each future taggable adds its own `<Entity>Tag` join to the **same** `Tag`; no GFK
ever enters the codebase, and no second Tag model either (the wanjala six-vocabulary duplication
is the other failure mode).

**Exact index set** (R3 — cover both hot directions, no redundant indexes):

- `UniqueConstraint(fields=["finding", "tag"], name="uniq_finding_tag")` — the identity; its
  backing B-tree serves hot query **"tags on these N findings"** (per-finding lookups and the
  list-page `prefetch_related`, which filters `finding_id IN (...)` — the constraint's leading
  column).
- `Index(fields=["workspace", "tag"], name="findingtag_ws_tag_idx")` — serves hot query
  **"findings having tag X in workspace W"**. AND-of-several-tags resolves as one probe of this
  index per tag (bitmap-AND / one `EXISTS` per tag group — D7); OR-of-several-tags is one probe
  with `tag_id IN (...)`.
- The `finding` and `workspace` FKs are declared `db_index=False` (each is the leading column of
  one of the two indexes above — a separate single-column index would be duplicate write cost,
  perf rule §6). The `tag` FK keeps Django's default FK index (`(workspace, tag)` does **not**
  prefix-cover tag-only lookups, and the FK integrity path needs it).

*Why this satisfies Explicit Architecture:* a GFK from a central `tagging` app into every taggable
table is exactly the reverse-coupling C4 forbids (it makes the tag store *know* every context's
internals via content-types). Per-context joins keep each taggable owning its own association,
FK-ing only the **shared vocabulary** — the same "correlate by shared value-identity, not by FK
into another context's guts" discipline the Finding↔Asset `asset_urn` link already uses (ADR 0004
D4).

### D2 — A new `tagging` bounded context owns the Tag vocabulary. **[locked — Henry confirmed: own bounded context]**

`components/tagging/` is a full bounded context (not a `shared_kernel` primitive): it has its own
CRUD API surface, lifecycle, and room to grow (governance toggle, merge, tag policies). It owns the
`Tag` entity, `TagStorePort`, and tag CRUD. It depends on nothing but workspace identity +
`shared_kernel`. Canonical layout (per `.claude/rules/bounded-context-structure.md`):

```
components/tagging/
    __init__.py
    api/
        __init__.py
        controller.py                    # TagListCreateView, TagDetailView
        urls.py                          # mounted at path("tagging/", ...) in api/urls.py
        requests/                        # CreateTagRequest, UpdateTagRequest, ListTagsRequest
        resources/                       # TagResource (dataclass DTO — findings-style, no DRF serializer)
    application/
        __init__.py
        service.py                       # thin front door (optional in P1 if use cases suffice)
        ports/
            tag_store_port.py            # TagStorePort (ABC) — THE seam other contexts consume
        use_cases/
            create_tag_use_case.py
            update_tag_use_case.py       # rename (re-slug) + color + description
            delete_tag_use_case.py       # soft delete
            list_tags_use_case.py
        commands/                        # CreateTagCommand, UpdateTagCommand, DeleteTagCommand
        providers/
            tagging_provider.py          # composition root: build_*_use_case(), build_tag_store()
    domain/
        __init__.py
        entities/
            tag_entity.py                # TagEntity (frozen dataclass)
        value_objects/
            tag_ref.py                   # TagRef (id, slug, name, color) — the cross-context read carrier
            tag_slug.py                  # normalize()/parse() — the ONE normalization implementation
        errors.py                        # TagNotFoundError, InvalidTagError, TagLimitExceededError,
                                         # ReservedTagError, DuplicateTagError
    infrastructure/
        __init__.py
        repositories/
            django_tag_repository.py     # implements TagStorePort
        services/
            workspace_access.py          # boundary-clean copy: is_workspace_member + is_workspace_admin
    mappers/
        __init__.py
        db/
            tag_mapper.py                # Tag ORM ↔ TagEntity / TagRef
    tests/
        unit/                            # slug normalization, entity invariants, limit guards
        integration/                     # CRUD API, uniqueness, soft-delete, query counts
```

ORM home: **`infrastructure/persistence/tagging/`** (new Django app — `models.py`, `apps.py`
(`name = "infrastructure.persistence.tagging"`), `admin.py`, `migrations/`), registered in
`INSTALLED_APPS` in `api/settings/base.py` next to `infrastructure.persistence.findings` (line
~122). The inherited `workspaces.Tag` is **not** the canonical Tag — it is fork-drift that leaks
tag vocabularies across tenants. Its retirement (the three legacy M2Ms + the global
`GET /workspace/tags/` endpoint + the grant JSONField tags) is **tracked in #83** and is NOT part
of this build. New code uses `tagging.Tag` exclusively.

### D3 — The `Tag` model: workspace-scoped, UUID PK, slug-identity, namespaced, coloured, soft-deleted. **[locked]**

`infrastructure/persistence/tagging/models.py` (house field order PK → FK → data → metadata):

```python
class ActiveTagManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Tag(models.Model):
    """One row per workspace-scoped vocabulary entry (ADR 0015 D3).

    Identity is (workspace, slug) among live rows. ``slug`` is the normalized
    ``namespace:value`` (or bare ``value``) key — the filter/API handle; ``name``
    is the display label. Platform-managed tags carry ``kind="system"``.
    """

    KIND_USER = "user"
    KIND_SYSTEM = "system"
    KIND_CHOICES = ((KIND_USER, "User"), (KIND_SYSTEM, "System"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="tag_vocabulary", db_index=False
    )
    name = models.CharField(max_length=64)          # display label, original casing, trimmed
    slug = models.CharField(max_length=100)          # normalized identity: "env:prod", "needs-review"
    namespace = models.CharField(max_length=32, blank=True, default="")  # "" = flat tag
    color = models.CharField(max_length=7, blank=True, default="")       # "#RRGGBB" or ""
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_USER)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    active = ActiveTagManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                condition=models.Q(is_deleted=False),
                name="uniq_tag_ws_slug_live",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "is_deleted"], name="tag_ws_deleted_idx"),
            models.Index(fields=["workspace", "namespace"], name="tag_ws_namespace_idx"),
        ]
```

Implementation notes the build agent must not miss:

- **`related_name` gotcha:** the legacy `Workspace.tags` M2M already claims the `tags` reverse
  accessor on `Workspace` — the new FK uses `related_name="tag_vocabulary"`.
- **`slug` is a `CharField`, not `SlugField`** — Django's `SlugField` validator rejects `:`, which
  the namespaced slug requires. Validation lives in the domain (`tag_slug.py`), not the field.
- The conditional unique constraint deliberately allows a live tag to coexist with a soft-deleted
  namesake (the ContactTag precedent). `get_or_create` (D6) considers **live rows only**.
- No `is_reserved` field. Reserved *namespaces* are a domain constant (D4) — they gate defaults
  and future automation, not writes; the only write gate is `kind="system"` (platform-only).

**Normalization rules** (one implementation, `components/tagging/domain/value_objects/tag_slug.py`
— every entry point uses it; grounded in R5/R6/R9/R14):

1. Input: a raw string, optionally `namespace:value` (first `:` splits; further `:` invalid).
2. Trim leading/trailing whitespace; collapse internal whitespace runs to a single space; strip
   control characters; Unicode NFC-normalize. This is the stored `name` (display).
3. `slug` = lowercase ASCII of the name: spaces → `-`, then restrict to
   `[a-z0-9]` with `- _ .` separators; must start and end alphanumeric (K8s rule, R6). Namespaced
   form: `namespace:value-slug`. Full validation regex:
   `^([a-z][a-z0-9_-]{0,31}:)?[a-z0-9][a-z0-9_.-]{0,62}[a-z0-9]$` (single-char values allowed:
   `^…(:)?[a-z0-9]$` degenerate case — implement as parse-then-validate, not one regex in the DB).
4. `namespace`: lowercase, `[a-z][a-z0-9_-]*`, ≤32 chars, must start with a letter (Datadog rule,
   R5). Empty for flat tags.
5. Dedup is **case-insensitive by construction** — `macOS` and `macos` normalize to the same slug
   and are one tag (the Jira failure mode, R9, designed out). Display keeps the casing of the
   *first* creation; rename fixes casing.
6. Empty-after-normalization ⇒ `InvalidTagError` (400).

**Limits** (enforced in use cases, returning 400/`TagLimitExceededError` — grounded in R4/R6/R8):

| Limit | Value | Grounding |
|---|---|---|
| `name` length | ≤ 64 chars | Between GitHub's 50 (R8) and K8s' 63 (R6); AWS allows 128 (R4) — 64 is ample for a chip UI |
| `slug` length (incl. namespace + `:`) | ≤ 100 chars | 32 + 1 + 64 + margin; well under Datadog's 200 (R5) |
| `namespace` length | ≤ 32 chars | Sentry key = 32 (R14) |
| Tags per finding | ≤ **50** | AWS: 50 tags/resource (R4); GitHub allows 100 (R8) — 50 is the security-industry analogue |
| Live tags per workspace | ≤ **1,000** | Sprawl guard (app-level, not a DB constraint); no product publishes one — 1,000 ≫ any sane vocabulary, cheap to raise |
| `color` | `""` or `^#[0-9a-fA-F]{6}$` | Hex only; HUD palette tokens resolve client-side |

### D4 — Vocabulary governance: free-form for members; `system` kind platform-only; destructive vocabulary ops admin-gated; curated-lock toggle specced now, shipped P2. **[locked — grounded in R6/R8/R10/R12]**

- **Create + apply/remove (on findings): any active workspace member.** GitHub's bar for label
  create/edit is repo write access (R8) — our analogue is workspace membership, and it matches the
  existing `FindingStatusView` gate ("any workspace member may act"). Free-form auto-create on
  first use (D6) keeps Tom's friction near zero.
- **Rename / recolor / delete / (P2) merge: workspace `role in ("owner", "admin")`.** These are
  destructive *vocabulary* operations that affect every member's saved views and filters — the
  Snyk precedent gates exactly this class of shared-state mutation to admins (R10). Implemented as
  `is_workspace_admin(user, workspace_id)` in `components/tagging/infrastructure/services/
  workspace_access.py` (boundary-clean copy of the findings helper, plus a
  `role__in=("owner", "admin")` filter on the membership row; staff/superuser passes).
- **`kind="system"` tags are platform-writable only** — user CRUD and the tag/untag endpoint
  reject create/rename/delete/apply-by-name of system tags (`ReservedTagError` → 400). This is the
  K8s `kubernetes.io/` reserved-prefix rule (R6). P1 ships the enforcement; no system tags exist
  yet in P1 (D8).
- **Reserved namespaces** (domain constant `RESERVED_NAMESPACES = ("owner", "team", "env",
  "service", "compliance", "risk")`): recognised for default colours (owner=blue, team=teal,
  env=amber, service=cyan, compliance=violet, risk=red — HUD tokens, frontend concern) and later
  automation/routing (R13: Wiz ownership tags, Datadog `env`/`service` unified tags). Operators
  MAY create tags in reserved namespaces (asserting `owner:payments` is the point); they may NOT
  create tags in the `risk:` namespace (held back for the platform — see D9's history) — enforce
  `risk:` as system-only from day one so no user data squats on it.
- **No same-key mutual exclusion in P1.** GitLab scoped labels auto-replace same-key labels (R7);
  we deliberately do NOT — a finding can carry `owner:platform` **and** `owner:payments` (shared
  ownership is real). Per-namespace exclusivity is a possible later per-namespace policy; do not
  build it now.
- **Curated-only lock (P2, specced now):** the AWS-tag-policies pattern (R12) — a per-workspace
  governance toggle `restrict_tag_creation` (when true, `get_or_create` on the tag/untag path
  returns `unknown_tag` 400 instead of creating; only admins create via CRUD). P2 adds
  `infrastructure/persistence/tagging/models.py::WorkspaceTagSettings` (`workspace` OneToOne,
  `restrict_tag_creation` bool default False). P1 does NOT create this table; the use-case code
  path reads an injected `allow_member_creation: bool = True` so P2 is a config-read, not a
  refactor.

### D5 — Lifecycle semantics: rename re-slugs (id is the stable identity); delete is soft and non-destructive to joins; merge is P2. **[locked — grounded in R8/R9/R15]**

- **Rename** (admin-gated): updates `name`, **re-derives `slug`** (and may change `namespace` only
  between "" and a non-reserved namespace), re-checks live uniqueness (`DuplicateTagError` → 409).
  Joins follow automatically (FK). Rename propagates everywhere instantly — the GitHub semantics
  (R8), and the exact thing Jira's unmanaged labels cannot do (R9). **Anything durable
  (workflow rule configs, saved views) MUST store `tag_id`, never the slug** — the slug is a
  display/API handle that renames can change; the UUID is the identity. This is a P1 contract
  written into the port docstring.
- **Delete** (admin-gated): **soft** — `is_deleted=True`. `FindingTag` rows are **retained**;
  every read path already joins `Tag` and filters `tag__is_deleted=False` (free — same JOIN), so a
  deleted tag disappears from chips and filters without destroying history. **Restore** (admin,
  P1-cheap: `PATCH` with `is_deleted=false`, subject to the live-uniqueness check) brings the tag
  *and all its assignments* back. Contrast GitHub, which hard-deletes label assignments (R8) — the
  soft path is house style and strictly more recoverable.
- **Usage count**: the CRUD list annotates `usage_count=Count("finding_links", filter=Q(...))` in
  the repository (perf rule §9 — never a per-row `SerializerMethodField` query). Displayed in the
  manage-tags UI and the delete confirmation ("this tag is on 37 findings").
- **Merge (P2, semantics locked now):** admin-gated `POST /tagging/workspaces/<ws>/tags/<loser_id>/merge/`
  `{into: <winner_id>}` — repoint `FindingTag.tag` from loser to winner (skipping rows where the
  winner already exists — the unique constraint), then soft-delete the loser. Real demand exists
  (R15) but it is cleanup tooling, not day-1 — and free-form creation plus case-folding slugs
  (D3) already prevents the main duplicate source.

### D6 — API surface. **[locked — mirrors the verified finding-status seam]**

**Tag CRUD (owned by `tagging`, mounted at `path("tagging/", include("components.tagging.api.urls"))`
in `api/urls.py`):**

| Endpoint | Gate | Contract |
|---|---|---|
| `GET /tagging/workspaces/<uuid:workspace_id>/tags/` | member | Query params: `namespace=` (exact), `q=` (icontains on name/slug), `include_usage=1` (adds `usage_count` via annotate), `limit` (default 200, max 500 — a tag picker needs the whole vocabulary, not 9/page), `offset`. Live tags only, ordered `slug`. → `{success, data: {items: [TagResource…], total}}` |
| `POST /tagging/workspaces/<ws>/tags/` | member | `{name, namespace?, color?, description?}` → 201 `{success, data: TagResource}`. Errors: `invalid_tag` 400, `duplicate_tag` 409, `tag_limit_exceeded` 400, `reserved_tag` 400 (system namespace). |
| `PATCH /tagging/workspaces/<ws>/tags/<uuid:tag_id>/` | **admin** | `{name?, color?, description?, is_deleted?}` — rename re-slugs (D5); `is_deleted: false` = restore. |
| `DELETE /tagging/workspaces/<ws>/tags/<uuid:tag_id>/` | **admin** | Soft delete. 204-style `{success: true}`. |

`TagResource` (dataclass DTO, findings-style): `{id, name, slug, namespace, color, description,
kind, usage_count?}`.

**Tag/untag a finding (owned by `findings` — the join lives with the entity it tags). ONE endpoint,
modeled 1:1 on `FindingStatusView`:**

```
POST /findings/workspaces/<uuid:workspace_id>/<uuid:finding_id>/tags/
Body: {"add": ["env:prod", "needs-review"], "remove": ["team:payments"]}
```

- Gate: `is_workspace_member` (same as status — any member acts).
- `add` / `remove` are lists of **slugs** (the human/API handle; the UI may also pass raw names —
  the use case normalizes via `tag_slug.py`). Both optional, at least one non-empty.
- `TagFindingUseCase` (`components/findings/application/use_cases/tag_finding_use_case.py`,
  command `TagFindingCommand(workspace_id, finding_id, add, remove, actor_id, at)`):
  1. Load the finding (404 `FindingNotFoundError` if absent/other-workspace).
  2. Resolve `remove` slugs via `TagStorePort.resolve_slugs` (unknown slugs are no-ops).
  3. Resolve `add` slugs via `TagStorePort.get_or_create` per slug (**auto-create** user tags on
     first use — D4; `ReservedTagError` 400 for `risk:`/system tags; `TagLimitExceededError` 400
     past 50 tags-per-finding or 1,000 per-workspace).
  4. Bulk-create missing `FindingTag` rows (`ignore_conflicts=True` — idempotent adds) with
     `source="user"`, `applied_by=actor_id`; delete removed rows (hard delete — the join is an
     edge, not a record; provenance is the audit log line, matching how status changes audit).
  5. `logger.info("finding_tagged workspace_id=%s finding_id=%s added=%s removed=%s actor_id=%s", …)`.
- Response: `{success: true, data: {id, tags: [TagRef…]}}` (the finding's full post-change tag set,
  so the HUD chip row re-renders from the response).
- No separate `DELETE …/tags/<tag_id>/` route — the single POST body subsumes it (matches the
  status endpoint's single-POST action shape).

### D7 — Filter semantics: AND across `tag` params, OR within a comma group, `exclude_tag` for negation — folded into the existing ranked read as indexed `EXISTS` subqueries. **[locked — grounded in R8 (GitHub qualifier algebra) + R5 (Datadog facet algebra)]**

The industry-consistent contract (GitHub: space-separated `label:` qualifiers AND, comma-OR within
one, `-label:` excludes, R8; Datadog: AND across facets, OR within a facet's values, R5):

**Query params on `GET /findings/workspaces/<ws>/`** (added to `ListFindingsRequest`):

- `tag=<slug>[,<slug>…]` — repeatable. **Each occurrence is an OR-group; occurrences AND
  together.** `?tag=env:prod,env:staging&tag=team:payments` = (env:prod OR env:staging) AND
  team:payments.
- `exclude_tag=<slug>` — repeatable; each excluded slug is AND-NOT. `?tag=kev-adjacent&exclude_tag=risk:accepted`.
- Unknown slugs: resolved slugs only participate; an unknown slug in an OR-group simply matches
  nothing (a group that resolves to zero tags ⇒ zero results — strict, deterministic, GitHub-like).
  Unknown `exclude_tag` slugs are no-ops.

**Port shape** — `list_findings`, `list_ranked_findings`, `count_findings` on `FindingStorePort`
each gain (defaults keep every existing caller source-compatible):

```python
tag_groups: tuple[tuple[UUID, ...], ...] = (),   # AND of OR-groups (already slug-resolved)
exclude_tag_ids: tuple[UUID, ...] = (),
```

The controller/request layer resolves slugs → UUIDs once via `TagStorePort.resolve_slugs` and
passes IDs down — the port stays framework-free and slug-agnostic. (This shape subsumes the
draft's `tag_match: any|all`: *all* = N singleton groups, *any* = one group. The draft's flat
`tag_ids` is **superseded**.)

**Repository resolution** (`DjangoFindingRepository`) — inside the SAME queryset that already
applies severity/status/source/asset_urn and the `FindingRisk` ordering (never a second code path,
never a resolve-then-`id__in` round trip):

```python
for group in tag_groups:
    qs = qs.filter(Exists(FindingTag.objects.filter(finding=OuterRef("pk"), tag_id__in=group)))
for tag_id in exclude_tag_ids:
    qs = qs.filter(~Exists(FindingTag.objects.filter(finding=OuterRef("pk"), tag_id=tag_id)))
```

`Exists()` subqueries — NOT chained M2M `.filter()` joins — so rows never multiply and no
`DISTINCT` is needed; each subquery is one probe of `findingtag_ws_tag_idx`-or-the-unique-index
(D1), keeping the read O(matched) at scale.

**Read path for tag chips on the list**: the repository `prefetch_related`es the join
(`Prefetch("tag_links", queryset=FindingTag.objects.select_related("tag").filter(tag__is_deleted=False))`)
so a page of N findings costs **one** extra query regardless of N (perf rule §1); the mapper
projects to `FindingEntity.tags: tuple[TagRef, ...]`. A query-count regression test guards it
(pattern: `components/team/tests/integration/test_*query_count.py`).

### D8 — System/derived tags: the column rule. A system tag may only exist where NO first-class column does. P1 ships the enforcement machinery and ZERO system tags. **[locked]**

The rule, now applied strictly to our own draft: `severity`, `status`, `source` are first-class
`Finding` columns and already filter params — they must **never** be mirrored as tags (a
`source:trivy` tag would be a second, driftable copy of `Finding.source`; the draft's example is
**rejected** by the draft's own rule). `kev` lives on `FindingRisk.in_kev` — also a column, also
not a tag. Consequently **P1 auto-stamps nothing**. What P1 ships is the *machinery*: `kind="system"`,
platform-only writes, and the reserved `risk:` namespace held back from users — so that when a
genuine column-less derived label appears (P3 automation stamps, e.g. a rule-applied
`team:payments` with `source="rule"`), it slots in without schema change. The `FindingTag.source`
provenance field (`user | agent | rule | system`) ships in P1 so agent/rule-applied tags are
distinguishable from day one (AI-actions-provenance principle).

### D9 — Risk acceptance: reason + optional expiry live on the finding's `suppress` lifecycle action. The derived `risk:accepted` tag is DROPPED. **[locked — research OVERTURNED the draft here; grounded in R10/R11]**

The draft proposed a system-managed `risk:accepted` tag auto-synced to suppressed findings. That
**violates D8's own column rule**: "suppressed" IS a first-class column (`Finding.status`), already
a filter param on every findings read, and already how saved views will filter status. A derived
tag would be a second source of truth requiring a sync job whose only failure mode is the two
disagreeing. **Dropped.** Saved views compose status filters and tag filters equally; nothing is
lost.

What the competitors actually productize — and what William asked for — is **ignore-with-reason,
time-boxed** (Snyk: categorised reason + hard `expires` timestamp, after which the finding
reappears as if never ignored, R10; DefectDojo: risk-acceptance expiration flips findings back to
Active, R11). Locked:

- `ChangeFindingStatusCommand` gains `reason: str = ""` and `expires_at: datetime | None = None`
  — valid only with `action="suppress"` (`InvalidFindingActionError` otherwise). The request body
  becomes `{"action": "suppress", "reason": "vendor-accepted; sandboxed", "expires_at": "2026-11-01T00:00:00Z"}`
  (both optional — keep the current one-click suppress working; the HUD SHOULD prompt for a
  reason).
- `Finding` gains two columns (migration in `infrastructure/persistence/findings/`):
  `status_reason = models.TextField(blank=True, default="")` and
  `suppress_expires_at = models.DateTimeField(null=True, blank=True)`. `resolve`/`reopen` clear
  both. **These fields ship in P1** (capture the data from day one — retrofitting reasons is
  impossible); the enforcement is P2.
- **P2 enforcement**: a Celery-beat task reopens suppressed findings whose `suppress_expires_at`
  has passed (status → `open`, reason retained for the audit trail, `logger.info` +
  notification) — the DefectDojo reactivation semantics (R11).
- `risk:` remains a reserved, user-locked namespace (D4) so this decision is reversible without
  data squatting on the name — but nothing populates it in P1/P2.

### D10 — `FindingTag` join (final shape). **[locked]**

`infrastructure/persistence/findings/models.py` (co-located with `Finding`; owned/written by the
findings context):

```python
class FindingTag(models.Model):
    """Tag assignment on a finding (ADR 0015 D10) — an edge, not a record.

    FKs the tagging context's vocabulary at the persistence ring (single-DB;
    cross-app ORM FKs are normal here — the component boundary governs
    ``components.*`` imports, not outermost-ring model relations).
    """

    SOURCE_CHOICES = (("user", "User"), ("agent", "Agent"), ("rule", "Rule"), ("system", "System"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="finding_tags", db_index=False)
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="tag_links", db_index=False)
    tag = models.ForeignKey("tagging.Tag", on_delete=models.CASCADE, related_name="finding_links")
    applied_by = models.UUIDField(null=True, blank=True)   # actor user id; null = platform (mirrors actor_id)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="user")
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["finding", "tag"], name="uniq_finding_tag")]
        indexes = [models.Index(fields=["workspace", "tag"], name="findingtag_ws_tag_idx")]
```

(`workspace` is denormalized from `finding` for the scoped index — the use case sets it from the
loaded finding, never from client input. The draft's `reason` column is dropped with D9's derived
tag; the draft's redundant `Index(finding)` is dropped per D1's index analysis.)

## The `TagStorePort` seam (what other contexts consume)

`components/tagging/application/ports/tag_store_port.py` — the ONLY way another context touches
the vocabulary (Rule 3: importing another context's `application.ports` + `domain` types is
allowed; its infrastructure is not):

```python
class TagStorePort(ABC):
    @abstractmethod
    def get_or_create(self, workspace_id: UUID, raw: str, *, kind: str = "user") -> TagEntity:
        """Normalize ``raw`` (name or namespace:name) and return the live tag, creating a
        ``user`` tag if absent. Raises InvalidTagError / ReservedTagError / TagLimitExceededError."""

    @abstractmethod
    def resolve_slugs(self, workspace_id: UUID, slugs: Sequence[str]) -> dict[str, UUID]:
        """Map normalized slugs → live tag ids. Unknown slugs are simply absent from the result."""

    @abstractmethod
    def refs_for_ids(self, workspace_id: UUID, tag_ids: Sequence[UUID]) -> tuple[TagRef, ...]: ...

    @abstractmethod
    def get_by_id(self, workspace_id: UUID, tag_id: UUID) -> TagEntity: ...   # TagNotFoundError

    @abstractmethod
    def list_for_workspace(
        self, workspace_id: UUID, *, namespace: str | None = None, q: str | None = None,
        with_usage: bool = False, limit: int = 200, offset: int = 0,
    ) -> tuple[list[TagEntity], int]: ...

    @abstractmethod
    def create(self, command: CreateTagCommand) -> TagEntity: ...

    @abstractmethod
    def update(self, command: UpdateTagCommand) -> TagEntity: ...   # rename re-slugs; restore via is_deleted=False

    @abstractmethod
    def soft_delete(self, workspace_id: UUID, tag_id: UUID) -> None: ...
```

Durable references (workflow rule configs, saved views) store **`tag_id`**, never slug (D5).

**Read-path boundary note (build agent, read twice):** the findings repository does NOT round-trip
through `TagStorePort` to render chips — `FindingTag` FKs `tagging.Tag` at the persistence ring,
and `DjangoFindingRepository` prefetches `tag_links__tag` directly (findings repositories already
import shared persistence models, e.g. `WorkspaceMembership`). The port is for **vocabulary
operations** (resolve/create/update) from other contexts' *application* layers; the ORM join is
the outermost ring doing its job. This is the same split the membership gate uses.

## Consequences

**Positive**
- One canonical, tenant-scoped tag vocabulary — the inherited cross-tenant leak is designed out.
- Fast, referential, index-backed tag-filtered finding queries; no GFK content-type indirection;
  both hot directions covered by exactly two indexes.
- DRY: findings, assets, tasks share ONE `Tag` + `TagStorePort`; each adds a thin join, not a Tag
  model — fixing wanjala's six-vocabulary duplication.
- Clean boundaries: tagging owns the vocabulary behind a port; each taggable owns its own join; no
  cross-context infrastructure import; no GFK reverse-coupling.
- Composes with (doesn't fork) the ranked read, the lifecycle SSOT, the compliance field, saved
  views, and the workflow engine. Risk acceptance lands on the lifecycle where Snyk/DefectDojo put
  it, with the expiry field captured from day one.

**Negative / costs**
- A new bounded context (`tagging`) — small, but real scaffolding (context + persistence app +
  migration + INSTALLED_APPS + URL mount).
- Two legacy tag surfaces linger (global `workspaces.Tag` M2Ms; grant JSONField tags) until #83
  retires them — dual-read risk fenced by "new code uses `tagging.Tag` exclusively".
- Each new taggable is a (small) explicit join + migration — the deliberate cost of avoiding the
  GFK.
- The per-workspace/per-finding limits are app-enforced, not DB-enforced — a direct-ORM writer
  could exceed them (acceptable; all writes flow through the use cases).

## P1 build plan (implementation grade — execute verbatim)

**New files / touchpoints:**

1. **Persistence app** `infrastructure/persistence/tagging/` (`__init__.py`, `apps.py` with
   `name = "infrastructure.persistence.tagging"`, `models.py` per D3, `admin.py` (register `Tag`,
   list_display name/slug/workspace/kind/is_deleted), `migrations/0001_initial.py` via
   `makemigrations`). Register in `api/settings/base.py` `INSTALLED_APPS` beside
   `infrastructure.persistence.findings`.
2. **`FindingTag`** in `infrastructure/persistence/findings/models.py` per D10 + **`Finding`
   columns** `status_reason`, `suppress_expires_at` per D9 → one findings migration.
3. **`components/tagging/`** per the D2 tree: `tag_slug.py` normalization (D3 rules, exhaustively
   unit-tested), `TagEntity` (frozen dataclass, invariants in `__post_init__`: name 1–64 after
   trim, valid slug/namespace, valid color, kind in choices), `TagRef` value object
   (`id`, `slug`, `name`, `color`), errors, `TagStorePort` (above), `DjangoTagRepository`
   (implements the port; `.active` manager; `usage_count` via annotate; all writes through
   mappers), use cases + commands + `TaggingProvider`, controller + urls + request/resource DTOs
   per D6, `workspace_access.py` with `is_workspace_member` + `is_workspace_admin` (D4).
4. **URL mount**: `path("tagging/", include("components.tagging.api.urls"))` in `api/urls.py`.
5. **Findings context**: `TagFindingCommand` + `TagFindingUseCase` (D6 algorithm), wired in
   `FindingProvider` (inject `TagStorePort` from `TaggingProvider`); `FindingTagView` in
   `components/findings/api/controller.py` + route in `components/findings/api/urls.py`
   (`workspaces/<uuid:workspace_id>/<uuid:finding_id>/tags/`); `ChangeFindingStatusCommand` +
   request + use case gain `reason`/`expires_at` (suppress-only validation; resolve/reopen clear
   the columns); `FindingEntity.tags: tuple[TagRef, ...] = ()`; `FindingStorePort` +
   `DjangoFindingRepository`: `tag_groups`/`exclude_tag_ids` on `list_findings` /
   `list_ranked_findings` / `count_findings` via `Exists()` per D7; chip prefetch per D7;
   `ListFindingsRequest` parses `tag`/`exclude_tag` params and resolves slugs via the port;
   `FindingResource` serializes `tags`.
6. **Tests**: unit — slug normalization table-driven (casing, whitespace, unicode, namespace
   parsing, reserved-namespace rejection, length limits), entity invariants, filter-param parsing;
   integration — tag CRUD (member vs admin gates, duplicate 409, soft-delete/restore,
   live-uniqueness with a dead namesake), tag/untag (auto-create, idempotent re-add, remove,
   50-tag limit, `risk:` rejection, cross-workspace 404), list filtering (AND-of-OR-groups,
   exclusion, unknown slugs), suppress with reason/expiry (+ validation on non-suppress);
   **query-count regression** — findings list with tags is constant w.r.t. rows AND w.r.t. tags
   per finding (create N findings × M tags, then more, assert equal counts — perf rule §1).
7. **Frontend (separate repo, after the API lands)**: Tag action on the #78 finding action row +
   chip row on the finding callout (add/remove via the D6 endpoint) + tag filter on the findings
   list/BRIEF. Reuse HUD chip primitives; namespace default colours per D4.

**Explicit P1 NON-goals (do not build):**
- `AssetTag` / `TaskTag` joins — **P3**.
- Tag **merge** — **P2** (semantics locked in D5).
- Suppress-expiry **enforcement** (the beat task) — **P2** (fields ship in P1).
- `WorkspaceTagSettings` / curated-lock toggle — **P2** (behavioral seam specced in D4).
- Any derived/system tag stamping (incl. `risk:accepted` — dropped, D9).
- Workflow `add_tag`/`remove_tag` rewiring onto the canonical vocabulary — **P3**.
- Touching the legacy `workspaces.Tag` surface / `GET /workspace/tags/` — **#83**, not here.
- Saved views — separate ADR; consumes D7's filter contract.

## P2 / P3 (deferred, shapes locked above)

- **P2**: suppress-expiry auto-reopen beat task (D9); tag merge endpoint (D5);
  `WorkspaceTagSettings.restrict_tag_creation` lock (D4); `compliance:` operator-asserted overlay
  unioned (labelled "operator-asserted" vs "scanner-derived") into the compliance summary
  (ADR 0009); sample-data mode ships sample tags (ADR 0011); saved views consume the tag filter.
- **P3**: `AssetTag` (cloud_graph) + `TaskTag` (board) joins on the same `Tag`; workflow
  `add_tag` action re-targeted to findings/assets with `source="rule"`; ownership routing
  (Wiz-style, R13) via `owner:`/`team:` tags; legacy tag-surface retirement lands via #83.

## Resolved questions (were "open" in the draft)

1. **Full bounded context vs shared-kernel primitive** → **full context** (Henry confirmed; D2).
2. **Where the risk-acceptance reason lives** → on the **status command/columns** (D9) — and the
   derived `risk:accepted` tag is dropped entirely, which research showed was the draft
   contradicting its own D8 column rule. Expiry (`expires_at`) is specced now, enforced P2.
3. **Free-form vs curated vocabulary** → **free-form for members** at GTM stage (GitHub-parity
   friction, R8), destructive ops admin-gated (Snyk precedent, R10), with the AWS-tag-policy-style
   curated lock (R12) specced as a P2 toggle.

[^lukeplant]: Luke Plant, *Avoid Django's GenericForeignKey* — no DB referential integrity, worse query plans. https://lukeplant.me.uk/blog/posts/avoid-django-genericforeignkey/
[^taggit]: django-taggit docs, *Customizing taggit* — concrete-FK through model for "the speed and referential guarantees of a real ForeignKey." https://django-taggit.readthedocs.io/en/latest/custom_tagging.html
[^contenttypes]: Django docs, *The contenttypes framework*. https://docs.djangoproject.com/en/6.0/ref/contrib/contenttypes/
[^tmk]: Tristan Kernan, *Django: Index Your Generic Foreign Keys* — GFKs are unindexed by default. https://blog.tmk.name/2025/09/06/django-index-your-generic-foreign-keys/
[^junction]: M2M junction design + composite-index prefix behaviour: https://www.beekeeperstudio.io/blog/many-to-many-database-relationships-complete-guide ; https://www.datacamp.com/blog/many-to-many-relationship
[^aws]: AWS, *Service quotas — Tagging AWS Resources* (50 tags/resource; key ≤128; value ≤256; charset; `aws:` reserved). https://docs.aws.amazon.com/tag-editor/latest/userguide/reference.html
[^datadog]: Datadog, *Getting Started with Tags* (≤200 chars; lowercase normalization; start with a letter; unified `env`/`service`/`version`). https://docs.datadoghq.com/getting_started/tagging/
[^k8s]: Kubernetes, *Labels and Selectors / Object names* (63-char names; charset; `kubernetes.io/`+`k8s.io/` reserved prefixes). https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/
[^gitlab]: GitLab docs, *Labels — scoped labels* (`key::value`, same-key mutual exclusion). https://docs.gitlab.com/user/project/labels/
[^gh]: GitHub docs, *Managing labels* (write access; rename propagates; <50-char names) + *Filtering and searching issues* (`label:` AND; comma OR; `-label:` exclude) + label-OR changelog. https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/managing-labels ; https://docs.github.com/en/issues/tracking-your-work-with-issues/filtering-and-searching-issues-and-pull-requests ; https://github.blog/changelog/2021-08-02-search-issues-by-label-using-logical-or/
[^jira]: Atlassian, *labels should be case insensitive* (JRACLOUD-24907) + JQL/case inconsistency (JRACLOUD-41181). https://jira.atlassian.com/browse/JRACLOUD-24907 ; https://jira.atlassian.com/browse/JRACLOUD-41181
[^snyk]: Snyk docs, *Ignore issues* (reason categories; admin-only restriction) + `snyk ignore --expiry --reason`; `.snyk` `expires` = hard timestamp, finding reappears on expiry. https://docs.snyk.io/manage-risk/prioritize-issues-for-fixing/ignore-issues ; https://docs.snyk.io/developer-tools/snyk-cli/commands/ignore
[^defectdojo]: DefectDojo docs, *Risk Acceptances* — expiration date; on expiry findings are set Active again. https://docs.defectdojo.com/triage_findings/findings_workflows/pro__risk_acceptance/
[^awspolicy]: AWS Organizations, *Tag policies* — centrally defined + enforced tag schema (allowed keys/values/casing). https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_tag-policies-enforcement.html
[^wiz]: Wiz, *Service Catalog / Reducing Risk through Service Ownership* — tagging + ownership as the basics; ownership tied to asset tags for finding routing. https://www.wiz.io/blog/wiz-service-catalog
[^orca]: Orca Security, *Risk-Based Vulnerability Management* — asset-criticality label feeding prioritization. https://orca.security/resources/blog/risk-based-vulnerability-management/
[^sentry]: Sentry docs, *Tags* — key ≤32 chars, value ≤200, key charset `a-zA-Z0-9_.:-`. https://docs.sentry.io/platforms/python/enriching-events/tags/
[^evernote]: Evernote user forums — multi-year *merge tags* feature-request threads. https://discussion.evernote.com/forums/topic/121360-tag-merging-grooming/
