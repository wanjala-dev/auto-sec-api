---
description: Persistence layer and ORM rules — where models live, who can access them, field ordering, migrations, and query optimization
globs: "**/models.py,**/repositories/**/*.py,**/mappers/db/**/*.py,**/migrations/**/*.py"
alwaysApply: false
---

# Persistence & ORM

## Where Models Live

All Django ORM models live in `infrastructure/persistence/`, organized by domain area. They are Django apps registered in `INSTALLED_APPS`. Models NEVER live inside `components/`.

```
infrastructure/persistence/
  users/models.py                    # CustomUser (AbstractUser, UUID PK, email auth)
  workspaces/models.py               # Workspace, WorkspaceMembership
  workspaces/payments/models.py      # PaymentMethod, PaymentPlan, PaymentEvent, PaymentOrder
  workspaces/aggregations/models.py  # Chart/aggregation data tables
  budget/models.py                   # Budget
  budget/transactions/models.py      # Transaction
  budget/categories/models.py        # Category
  sponsorship/donations/models.py    # Donation, DonationNotification
  sponsorship/sponsors/models.py     # Sponsor, Sponsorship
  sponsorship/recipients/models.py   # Recipient
  sponsorship/campaign/models.py     # Campaign
  sponsorship/events/models.py       # Event
  project/models.py                  # Project, Task
  team/models.py                     # Team, TeamMembership
  receipts/models.py                 # Receipt
  marketplace/store/models.py        # Store, Product
  marketplace/orders/models.py       # MarketplaceOrder
  ...
```

Each persistence app has:
- `models.py` — Django ORM model definitions
- `apps.py` — Django app config
- `admin.py` — Django admin registration
- `migrations/` — Database migrations

## Model Access Boundaries

The persistence layer is the **outermost ring**. Only infrastructure-level code touches ORM models.

### CAN import ORM models:

| Layer | Why |
|-------|-----|
| `infrastructure/repositories/` | Implements ports — this is WHERE ORM queries live |
| `mappers/db/` | Translates ORM model instances ↔ domain entities |
| `infrastructure/adapters/` | External service integrations that need DB access |
| `infrastructure/tasks/` | Celery tasks (background jobs) |
| `mappers/rest/` (serializers) | DRF serializers need model references |
| `infrastructure/management/` | Management commands |

### MUST NOT import ORM models:

| Layer | Use Instead |
|-------|-------------|
| `application/use_cases/` | Depend on ports (ABCs), injected repositories |
| `application/services/` | Same — ports only |
| `domain/entities/` | Domain is framework-free. No Django imports. |
| `domain/services/` | Same |
| `api/controller.py` | Use serializers and application services |

```python
# WRONG — use case imports ORM model
from infrastructure.persistence.sponsorship.donations.models import Donation
donation = Donation.objects.get(id=donation_id)

# CORRECT — use case depends on port
class ProcessDonationUseCase:
    def __init__(self, donation_store: DonationStorePort):
        self._store = donation_store

    def execute(self, donation_id: UUID):
        donation = self._store.find_by_id(donation_id)
        ...

# Repository implements the port
class DonationRepository(DonationStorePort):
    def find_by_id(self, donation_id):
        from infrastructure.persistence.sponsorship.donations.models import Donation
        obj = Donation.objects.filter(id=donation_id).first()
        return to_donation_entity(obj) if obj else None
```

### Known Tech Debt

Some use cases currently import models directly (e.g., `process_stripe_donation_ingest_event_use_case.py`). These are tracked violations. New code MUST NOT add more.

## Model Field Ordering

Order fields consistently: PK → FK/relations → data fields → metadata

```python
class Transaction(StandardMetadata):
    # 1. PK (usually inherited from StandardMetadata)
    # 2. FK / relations
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    donation = models.OneToOneField(Donation, on_delete=models.SET_NULL, null=True)
    recipient = models.ForeignKey(Recipient, on_delete=models.SET_NULL, null=True)
    # 3. Data fields
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    source_type = models.CharField(max_length=32)
    status = models.CharField(max_length=20)
    # 4. Metadata (created, modified, is_deleted inherited from StandardMetadata)
```

## Query Optimization

### Always use select_related / prefetch_related

```python
# CORRECT — in repository
Transaction.active.filter(
    workspace_id=workspace_id
).select_related(
    "workspace", "donation", "recipient", "category", "budget"
).prefetch_related(
    "donation__events"
)

# WRONG — bare query causing N+1
Transaction.objects.filter(workspace_id=workspace_id)
```

- `select_related()` for FK and OneToOne (single JOIN)
- `prefetch_related()` for M2M and reverse FK (separate query, cached)

### Use Active Managers

Many models have `.active` managers that filter soft-deleted records:

```python
Transaction.active.filter(...)   # NOT Transaction.objects.filter(is_deleted=False)
Budget.active.filter(...)
```

### No Raw SQL in Application Code

Raw SQL is only acceptable in management commands for schema operations. Everything else uses the ORM.

## Migrations

- Live in `infrastructure/persistence/<app>/migrations/`
- Create after any model change: `python manage.py makemigrations`
- Pytest skips migrations (`django_db_use_migrations = False`)
- Multi-database routing via `tenants.router.TenantRouter` — know which database your model lives on (default, workspace, art, linkthegap)
- Always test migrations locally before pushing: `python manage.py migrate`

## Signal Bridges (Model Lifecycle)

Model lifecycle hooks (post_save, pre_delete) are NOT defined on models. They use **signal bridges** — dedicated adapter classes in `infrastructure/adapters/`:

```python
# infrastructure/adapters/django_budget_signal_bridge.py
class DjangoBudgetSignalBridge:
    @staticmethod
    def register():
        post_save.connect(
            _handle_transaction_save,
            sender=Transaction,
            dispatch_uid="budgeting:transaction_post_save",
        )
```

Registered via `apps.py` `ready()` hooks. Never use `@receiver` decorator.
