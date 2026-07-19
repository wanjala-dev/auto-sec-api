---
description: Explicit Architecture manifesto — strict structural rules based on Herberto Graça's Explicit Architecture. Applies to all Python files.
globs: "**/*.py"
alwaysApply: true
---

# Architecture Manifesto

This project follows **Explicit Architecture** as defined by Herberto Graça:
https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/

These rules are **non-negotiable**. Violations must be fixed immediately, not deferred.

---

## Rule 1: Ports Live INSIDE the Application Layer

> "This layer contains Application Services (and their interfaces) as first class citizens, but it also contains the Ports & Adapters interfaces (ports)" — Herberto Graça

**Ports (interfaces/ABCs) MUST live in `components/<context>/application/ports/`.**

They MUST NOT live at the context root (`components/<context>/ports/`). This was corrected in April 2026 after 200+ port files were misplaced at root level.

```
# CORRECT
components/sponsorship/application/ports/donation_payment_store_port.py

# WRONG — never do this
components/sponsorship/ports/donation_payment_store_port.py
```

**Why**: Ports define how the Application Core communicates with the outside world. They are owned by the application layer, not the context root. Placing them at root level blurs the boundary between application concerns and infrastructure concerns.

## Rule 2: Dependencies Point Inward

```
Infrastructure → Application → Domain
     ↑                ↑            ↑
  (outer)          (middle)     (inner)
```

- **Domain** depends on NOTHING. No Django, no DRF, no ORM, no infrastructure.
- **Application** depends on Domain only. Ports are defined here. No framework imports.
- **Infrastructure** depends on Application (implements ports) and Domain (uses entities).
- **API/CLI/Workers** depend on Application only. They are primary adapters.

**Never import inward layers from outward layers:**
```python
# WRONG — domain importing from infrastructure
from infrastructure.persistence.users.models import CustomUser  # in a domain file

# WRONG — application importing from infrastructure
from components.sponsorship.infrastructure.repositories.donation_repository import ...  # in a use case

# CORRECT — infrastructure implementing a port
from components.sponsorship.application.ports.donation_store_port import DonationStorePort
class DonationRepository(DonationStorePort):
    ...
```

## Rule 3: Cross-Context Communication Rules

Components (bounded contexts) MUST NOT import each other's infrastructure:

```python
# WRONG — direct cross-context infrastructure import
from components.payments.infrastructure.repositories.payment_repo import PaymentRepo

# CORRECT — use ports, domain events, or shared kernel
from components.shared_kernel.domain.events import PaymentSucceeded
```

Allowed cross-context imports:
- `components.<other>.application.ports.*` — using another context's public interface
- `components.<other>.domain.entities.*` — reading another context's domain types
- `components.<other>.domain.events.*` — listening to domain events
- `components.shared_kernel.*` — shared types, events, utilities

## Rule 4: Primary Adapters Are Thin

Primary adapters (`api/controller.py`, `cli/`, `workers/tasks.py`) contain NO business logic. They:
1. Parse input (requests, CLI args, task params)
2. Call a use case or application service
3. Return output (response, exit code)

```python
# CORRECT — thin controller
class CheckoutController(APIView):
    def post(self, request, workspace_id):
        command = CreateCheckoutCommand.from_request(request)
        result = self._use_case.execute(command)
        return Response(CheckoutResource.from_result(result))

# WRONG — business logic in controller
class CheckoutController(APIView):
    def post(self, request, workspace_id):
        amount = Decimal(request.data['amount'])
        if amount < 10:
            raise ValidationError("Minimum $10")
        donation = Donation.objects.create(amount=amount, ...)  # ORM in controller!
```

## Rule 5: Secondary Adapters Implement Ports

Infrastructure adapters (repositories, gateways, external service clients) MUST implement a port interface:

```python
# Port (in application/ports/)
class DonationStorePort(ABC):
    @abstractmethod
    def save(self, donation: DonationEntity) -> None: ...

# Adapter (in infrastructure/repositories/)
class DjangoOrmDonationRepository(DonationStorePort):
    def save(self, donation: DonationEntity) -> None:
        DonationModel.objects.update_or_create(...)
```

## Rule 6: Domain Entities Are Frozen Dataclasses

Domain entities are immutable. They contain business logic but no framework code:

```python
@dataclass(frozen=True)
class DonationEntity:
    id: UUID
    workspace_id: UUID
    amount: Decimal
    currency: str
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
```

## Rule 7: Mappers Bridge Layers

Data transformation between layers happens in `mappers/`:
- `mappers/db/` — ORM model ↔ domain entity (used by repositories)
- `mappers/rest/` — API request/response ↔ domain DTOs (used by controllers)

Mappers are NOT business logic. They are mechanical translation.

## Rule 8: Bounded Context Structure

Every bounded context MUST have this structure:

```
components/<context>/
  api/                       # Primary adapter (REST)
  cli/                       # Primary adapter (management commands)
  workers/                   # Primary adapter (Celery task shim)
  application/               # Use cases, services, ports
    ports/                   # ALL port interfaces live HERE
    use_cases/
    ...
  domain/                    # Business logic, entities, events
  infrastructure/            # Secondary adapters (DB, Stripe, email)
  mappers/
    db/                      # ORM ↔ domain mappers
    rest/                    # DRF serializers
  tests/
```

## Rule 9: Providers Live in the Application Layer

> Providers are composition roots — they decide which adapter implements which port. This is a **policy decision**, which is an application concern, NOT an infrastructure concern.

**Providers MUST live in `components/<context>/application/providers/`.**

They MUST NOT live in `components/<context>/infrastructure/providers/`. Infrastructure should only implement ports, not decide which implementation to use.

```
# CORRECT
components/payments/application/providers/payment_gateway_provider.py
components/knowledge/application/providers/ai_llm_provider.py
components/shared_platform/application/providers/search_provider.py

# WRONG — never do this
components/knowledge/infrastructure/providers/ai_llm_provider.py
```

**Why**: Per Herberto Graça's Explicit Architecture, the Application Layer "contains Application Services (and their interfaces) as first class citizens, but it also contains the Ports & Adapters interfaces (ports)." Providers wire ports to adapters — that wiring logic is owned by the application layer. Placing providers in infrastructure inverts the dependency direction and means infrastructure is making policy decisions about itself.

## Rule 10: Controllers MUST NOT Import Infrastructure SDKs

Primary adapters (controllers, CLI, workers) MUST NOT import infrastructure SDKs directly. All infrastructure access goes through ports.

```python
# WRONG — controller imports Stripe SDK
import stripe
stripe.PaymentMethod.list(customer=cid)

# WRONG — controller imports LangChain
from langchain.schema import HumanMessage
llm([HumanMessage(content=message)])

# WRONG — controller imports elasticsearch_dsl
from elasticsearch_dsl import Q as ESQ
ESQ("multi_match", query=query, fields=fields)

# CORRECT — controller calls through port
gateway = payment_provider.get_gateway("stripe")
result = gateway.list_customer_payment_methods(customer_id=cid)

# CORRECT — controller calls through port
result = llm_port.chat([{"role": "user", "content": message}])

# CORRECT — controller calls through port
result = search_adapter.search(index="users", query=query, fields=fields)
```

**Why**: If a controller imports `stripe`, `langchain`, or `elasticsearch_dsl`, it couples the API layer to a specific vendor. Changing vendors means changing controllers — the exact problem ports solve. The adapter handles the SDK; the controller only talks to the port.

## Historical Lessons

### Ports Misplacement (Fixed April 2026)
200+ port files were placed at `components/<context>/ports/` (context root) instead of `components/<context>/application/ports/`. This violated the Explicit Architecture principle that ports belong in the Application Layer. All files were moved and 557 import paths were rewritten. This rule exists to prevent recurrence.

### Providers Misplacement (Fixed April 2026)
5 provider files were placed in `components/<context>/infrastructure/providers/` instead of `components/<context>/application/providers/`. This violated the principle that composition root / wiring logic belongs in the Application Layer. 4 Knowledge providers and 1 Sponsorship provider were moved, and 17 import paths were rewritten.

### Controller SDK Imports (Fixed April 2026)
20+ direct SDK imports (`import stripe`, `from langchain`, `from elasticsearch_dsl`) were found in 4 controllers (payments, knowledge, agents, shared_platform). All were refactored to go through their respective ports. This rule exists to prevent recurrence.

### Source Type Labeling (Fixed April 2026)
Adding a new payment source type requires updates in 6+ places (enum, tasks, tests, query, repository, receipt handler). The `TransactionSourceType` domain enum in `components/budgeting/domain/enums.py` is the canonical source of truth. Missing it causes silent validation failures.
