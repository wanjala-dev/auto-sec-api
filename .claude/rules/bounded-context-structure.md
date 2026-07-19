---
description: Canonical bounded context directory structure — the SINGLE SOURCE OF TRUTH for how every context is organized. All other docs reference this file.
globs: "components/**/*.py"
alwaysApply: true
---

# Bounded Context Structure (Canonical)

**This is the single source of truth for how bounded contexts are organized.**
Do not duplicate this tree in other files — reference this rule instead.

Every bounded context under `components/<context>/` MUST follow this structure:

```
components/<context>/
    __init__.py
    api/                           # PRIMARY ADAPTER: REST (driving side)
        __init__.py
        controller.py              # ONE file — all HTTP endpoints
        urls.py                    # ONE file — all routes
        permissions.py             # Optional — context-specific DRF permissions
        requests/                  # Input DTOs (frozen dataclasses)
        resources/                 # Output DTOs (frozen dataclasses)
    cli/                           # PRIMARY ADAPTER: CLI (driving side)
        __init__.py
        apps.py
        management/
            commands/
    workers/                       # PRIMARY ADAPTER: Scheduled tasks (driving side)
        __init__.py
        tasks.py                   # Celery Beat entry points — thin wrappers
    application/                   # USE CASES — framework-free orchestration
        __init__.py
        service.py                 # Orchestrator — single front door
        ports/                     # ⚠️  ALL port interfaces (ABCs) live HERE
        use_cases/                 # Individual extracted use case files
        handlers/                  # Application event handlers (side effects)
        commands/                  # Mutation DTOs (frozen dataclasses)
        queries/                   # Read DTOs
        providers/                 # ⚠️  Dependency factories / composition root
        facades/                   # Cross-context workflow orchestrators
        policies/                  # Application-level policy evaluators
        config/                    # Feature config / toggles
    domain/                        # BUSINESS LOGIC — no framework imports
        __init__.py
        entities/                  # Aggregate roots (frozen dataclasses)
        value_objects/             # Immutable domain concepts
        services/                  # Domain logic spanning entities
        policies/                  # Business rule evaluators
        events/                    # Domain events (immutable facts, past tense)
        errors.py                  # Context-specific exceptions
    infrastructure/                # SECONDARY ADAPTERS (driven side)
        __init__.py
        repositories/              # Port implementations (DB access)
        adapters/                  # Port implementations (external services)
        gateways/                  # Complex external integrations
        services/                  # Infrastructure services
        tasks/                     # Celery task definitions (implementations)
        management/                # Infra-only commands (backfills, schema)
    mappers/
        __init__.py
        db/                        # ORM model ↔ domain entity mappers
        rest/                      # DRF serializers (API ↔ domain DTOs)
    tests/
        unit/                      # No DB, no framework — pure logic
        integration/               # Full stack with DB
```

## Critical placement rules

| What | WHERE it lives | WHERE it NEVER lives |
|------|---------------|---------------------|
| Ports (ABCs/interfaces) | `application/ports/` | ~~`ports/`~~ (context root) |
| Providers (composition root) | `application/providers/` | ~~`infrastructure/providers/`~~ |
| Controllers | `api/controller.py` | Never split across multiple files |
| URL routing | `api/urls.py` | Never split across multiple files |
| ORM models | `infrastructure/persistence/` (separate Django app) | Never inside `components/` |

## What does NOT exist under `infrastructure/`

- ~~`infrastructure/providers/`~~ — Providers are composition roots (policy decisions). They live in `application/providers/`.
- ~~`infrastructure/serializers/`~~ — DRF serializers live in `mappers/rest/`.

## Rules

1. **ONE `controller.py`** — all HTTP endpoints in one file. If it grows past ~800 lines, split the bounded context, not the controller.
2. **ONE `urls.py`** — all URL routing in one file.
3. **ONE `service.py`** — the application layer's single front door.
4. **Providers in `application/providers/`** — they decide which adapter implements which port. This is a policy decision owned by the application layer.
5. **Ports in `application/ports/`** — they define how the application core communicates with the outside world. Ports are designed to fit the Application Core needs, NOT to mimic tool APIs (Herberto Graça).
6. **No shims, no re-exports** — every import points to the owning location. If code moves, update all consumers. Delete old files.
7. **Controllers are thin** — parse request, call service/use case, return response. No business logic, no SDK imports (`import stripe`, `from langchain`, `from elasticsearch_dsl` etc.)

## Events (per Herberto Graça's Explicit Architecture)

Events are categorized by layer and scope:

| Event type | Where it lives | What it represents | Scope |
|---|---|---|---|
| **Domain Events** | `domain/events/` | An immutable fact about something that happened in the domain (past tense: `DonationReceived`, `RecipientCreated`) | Within the bounded context |
| **Application Events** | Triggered by `application/handlers/` | An outcome of a use case — side effects like sending emails, notifications, starting other use cases | Within the bounded context |
| **Shared Events** | `components/shared_kernel/domain/events/` | Events shared across bounded contexts for decoupling. Components depend on the Shared Kernel, not on each other. | Cross-context |

**Key principles from Graça:**
- Domain Events are triggered when entity data changes — they carry the changed values
- Application Events are triggered after a use case completes — they represent side effects
- To decouple components, events live in the **Shared Kernel**, not in the originating component. This prevents component B from knowing about component A's internals.
- Cross-context communication uses events + Shared Kernel. Direct cross-context infrastructure imports are forbidden.
