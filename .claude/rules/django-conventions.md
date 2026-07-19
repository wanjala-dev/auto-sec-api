---
description: Django coding conventions — architecture, ORM, views, testing, and error handling standards for the Wanjala API
globs: "**/*.py"
alwaysApply: false
---

# Django Coding Conventions

This project uses **Django 6.0** with **Explicit Architecture** (DDD + Ports & Adapters + CQRS). It is NOT a standard MVT Django app. Follow these conventions, not generic Django tutorials.

## Architecture — Explicit Architecture, Not MVT

This project does NOT use Model-View-Template. Every bounded context follows the canonical structure defined in **`.claude/rules/bounded-context-structure.md`** — that file is the single source of truth for directory layout. Do not duplicate the tree here.

### Layer Rules (enforced by architecture tests in tests/architecture/)

- **Controllers are THIN** — parse request, call use case, return response. No business logic.
- **Application layer NEVER imports Django or DRF** — framework-free orchestration.
- **Domain entities are frozen dataclasses** — immutable, no ORM, no Django imports.
- **No cross-context infrastructure imports** — use ports, domain events, or shared kernel.
- **Business logic lives in domain entities and domain services** — not in views, serializers, or models.

## Views — Class-Based Only

Use DRF class-based views exclusively. No function-based views.

```python
# CORRECT — DRF generic or APIView
class RecipientListView(generics.ListAPIView):
    ...

class CheckoutController(APIView):
    def post(self, request):
        ...

# WRONG — function-based view
@api_view(['GET'])
def list_recipients(request):
    ...
```

**Preferred view types** (in order of preference):
1. `generics.ListAPIView`, `generics.RetrieveAPIView`, etc. — for standard CRUD
2. `APIView` — for custom endpoints (checkout, webhooks)
3. `ViewSet` — only when router-based URL generation is needed

## User Model

The project extends `AbstractUser` with `CustomUser` (UUID primary key, email-based auth). Never reference `django.contrib.auth.User` directly.

```python
# CORRECT
from infrastructure.persistence.users.models import CustomUser
AUTH_USER_MODEL = 'users.CustomUser'

# WRONG
from django.contrib.auth.models import User
```

## Authentication — JWT, Not Sessions

All auth uses `rest_framework_simplejwt.authentication.JWTAuthentication`. No session auth in the API.

```python
# Permission classes on views:
permission_classes = (permissions.IsAuthenticated,)          # Most endpoints
permission_classes = (permissions.IsAuthenticatedOrReadOnly,)  # Public read
```

## ORM — Avoid N+1 Queries

### Always use select_related/prefetch_related in repositories

```python
# CORRECT — in repository method
def list_transactions(self, workspace_id):
    return (
        Transaction.active
        .filter(workspace_id=workspace_id)
        .select_related("workspace", "donation", "recipient", "category", "budget")
        .order_by("-created")
    )

# WRONG — bare .all() or .filter() without related optimization
def list_transactions(self, workspace_id):
    return Transaction.objects.filter(workspace_id=workspace_id)
```

### Use active managers, not .filter(is_deleted=False)

Many models have `.active` managers. Use them:
```python
Transaction.active.filter(...)   # NOT Transaction.objects.filter(is_deleted=False, ...)
Budget.active.filter(...)
```

### No raw SQL in application code

Raw SQL is only acceptable in management commands for schema operations. Use the ORM everywhere else.

```python
# WRONG in a repository or service
cursor.execute("SELECT * FROM ...")

# CORRECT
Transaction.objects.filter(...).aggregate(Sum('amount'))
```

## Serializers — In mappers/rest/, Not in views

Serializers live in `mappers/rest/` (not inline in controllers). They handle data transformation only — no business logic.

```python
# File: components/sponsorship/mappers/rest/donations_serializers.py
class DonationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donation
        fields = [...]
```

## Signals — Use Signal Bridges, Not @receiver

Signals are registered via explicit `post_save.connect()` in dedicated bridge classes, called from app `ready()` hooks. Never use the `@receiver` decorator.

```python
# CORRECT — signal bridge in infrastructure/adapters/
class DjangoBudgetSignalBridge:
    @staticmethod
    def register():
        post_save.connect(
            _handle_transaction_save,
            sender=Transaction,
            dispatch_uid="budgeting:transaction_post_save",
        )

# In apps.py ready():
DjangoBudgetSignalBridge.register()

# WRONG — @receiver decorator
@receiver(post_save, sender=Transaction)
def handle_transaction_save(sender, instance, **kwargs):
    ...
```

## Domain Entities — Frozen Dataclasses

Domain entities are immutable dataclasses with validation in `__post_init__`:

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

## Error Handling

- **Never silence errors** — errors are signals, not noise
- **Fix root causes** — no band-aid try/except that swallows exceptions
- **Custom exception handler** is registered at `infrastructure.api.exception_handler.custom_exception_handler`
- **Log full tracebacks** with `logger.exception()`, never `logger.error(str(e))`

```python
# CORRECT
try:
    result = stripe.PaymentIntent.retrieve(pi_id)
except stripe.error.StripeError:
    logger.exception("Failed to retrieve PaymentIntent %s", pi_id)
    raise

# WRONG — swallowing the error
try:
    result = stripe.PaymentIntent.retrieve(pi_id)
except Exception:
    pass  # Never do this
```

## Testing — pytest, Not unittest

Use pytest with `@pytest.mark.django_db` for DB tests. Use the fixture factories from `conftest.py`.

```python
@pytest.mark.django_db
class TestDonationTransactionSync:
    def test_creates_income_transaction(self, workspace_factory):
        workspace = workspace_factory()
        donation = Donation.objects.create(amount=Decimal("25.00"), workspace=workspace)
        assert donation.transaction is not None
        assert donation.transaction.source_type == "donation"
```

**Test markers**: `@pytest.mark.unit` (no DB), `@pytest.mark.integration` (full DB), `@pytest.mark.arch` (architecture rules)

**Available fixtures**: `workspace_factory`, `user_factory`, `recipient_factory`, `team_factory`, `api_client`, `payment_workspace`

## Model Field Ordering

Order fields by: PK → FK/relations → data fields → metadata fields

```python
class Transaction(StandardMetadata):
    # PK (inherited from StandardMetadata)
    # FK / relations
    workspace = models.ForeignKey(Workspace, ...)
    donation = models.OneToOneField(Donation, ...)
    recipient = models.ForeignKey(Recipient, ...)
    # Data fields
    amount = models.DecimalField(...)
    currency = models.CharField(...)
    source_type = models.CharField(...)
    status = models.CharField(...)
    # Metadata (inherited: created, modified, is_deleted)
```

## Dependencies — What We Actually Use

| Category | Package | Version |
|----------|---------|---------|
| Framework | Django | 6.0 |
| API | djangorestframework | 3.15+ |
| Auth | djangorestframework-simplejwt | 5.5 |
| Auth/Social | django-allauth, dj-rest-auth | 65.3+, 7.2 |
| Async | celery | 5.4 |
| Broker/Cache | redis | via django-redis |
| Search | django-elasticsearch-dsl | 8.0 |
| AI/Agents | langchain, langchain-openai, langgraph | 0.3+ |
| Payments | stripe | 5.0 |
| Database | PostgreSQL via psycopg 3.2 (4 databases, tenant routing) |
| Schema | drf-spectacular | 0.29 |
| Filtering | django-filter | 24.2 |
| PDF | reportlab | (receipt generation) |
| Linting | ruff | (Black-compatible, line-length 120) |
| Testing | pytest, pytest-django | |

## Multi-Database Routing

4 PostgreSQL databases routed by `tenants.router.TenantRouter`. Always be aware of which database a model lives on. Never assume `default`.

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Controller | `controller.py` (one per context) | `components/payments/api/controller.py` |
| Request | `<noun>_request.py` in `api/requests/` | `transaction_request.py` |
| Resource | `<noun>_resources.py` in `api/resources/` | `transaction_resources.py` |
| Permissions | `permissions.py` in `api/` | `components/sponsorship/api/permissions.py` |
| Service | `service.py` | `components/sponsorship/application/service.py` |
| Use case | `<verb>_<noun>_use_case.py` | `process_stripe_donation_ingest_event_use_case.py` |
| Command | `<verb>_<noun>_command.py` | `create_workspace_donation_checkout_command.py` |
| Query | `<verb>_<noun>_query.py` | `financial_aggregations_query.py` |
| Port | `<noun>_port.py` in `application/ports/` | `donation_payment_store_port.py` |
| Repository | `<noun>_repository.py` | `donation_payment_repository.py` |
| Entity | `<noun>_entity.py` | `donation_entity.py` |
| DB Mapper | `<noun>_mapper.py` in `mappers/db/` | `transaction_mapper.py` |
| REST Serializer | `<noun>_serializers.py` in `mappers/rest/` | `donations_serializers.py` |

## Performance

- Use `select_related()` for FK/OneToOne, `prefetch_related()` for M2M/reverse FK
- Use active managers (`.active`) instead of filtering `is_deleted=False`
- Use Celery for any operation >100ms (Stripe calls, email, PDF generation, embeddings)
- Use Django cache (Redis backend) for frequently read data
- Pagination default is 9 items per page via `PageNumberPagination`
