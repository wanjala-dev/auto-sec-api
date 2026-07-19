---
description: Django ORM + query performance standards — eager loading, N+1 prevention, indexes, caching, and diagnosis
globs: "**/*.py"
alwaysApply: false
---

# Performance Standards

Rules for writing Django / DRF / Celery code that doesn't accidentally become slow. Apply to every new repository, serializer, signal bridge, and background task. Loosely modeled on Themis's internal playbook, adapted for Python + Django.

**Mental model:** query count scales with code paths, not with data. An endpoint that fires 1 query for 10 rows and 1 query for 10,000 rows is correct. An endpoint that fires 10 queries for 10 rows is an N+1 — it gets 100× worse as data grows and degrades silently.

## 1. Repositories eager-load what their serializer reads

Any repository method that returns a queryset destined for a serializer MUST eager-load every FK/OneToOne the serializer touches via `select_related()`, and every reverse FK/M2M via `prefetch_related()`.

Without this, a paginated page of 9 rows with a serializer that touches 6 FKs fires 54+ queries.

### How to audit a serializer

For each field on the serializer, classify:

| Field type | Access path | Fix |
|---|---|---|
| `SlugRelatedField(queryset=Foo)` | `obj.foo.<slug_field>` — forward FK | `select_related("foo")` |
| Nested `SomeSerializer()` on an FK | `obj.related` — forward FK | `select_related("related")` |
| `SerializerMethodField` that reads `obj.x.y` | Chained FK | `select_related("x", "x__y")` |
| `SerializerMethodField` that reads `obj.x_set.all()` | Reverse FK or M2M | `prefetch_related("x_set")` |
| OneToOne reverse (e.g. `obj.receipt`) | Reverse OneToOne | `select_related("receipt")` — still a JOIN |
| `ChoiceField`, plain `CharField`, etc. | Own column, no join | Nothing needed |

```python
# CORRECT — repository centralises the eager-load so every caller benefits
class TransactionReadRepository:
    def _base_queryset(self, query):
        return Transaction.active.filter(workspace=query.workspace_id).select_related(
            "category", "budget", "user", "workspace",
            "project", "receipt", "recipient",
        )

# WRONG — serializer touches 6 FKs; 9-row page = 54+ queries
class TransactionReadRepository:
    def _base_queryset(self, query):
        return Transaction.active.filter(workspace=query.workspace_id)
```

**Reference:** `components/budgeting/infrastructure/repositories/transaction_read_repository.py::_base_queryset`.

**Guard it:** every list-serving queryset/serializer change ships with a query-count regression test — `CaptureQueriesContext`, assert the count is constant w.r.t. row count (create N rows, then more, assert equal — never a brittle absolute number). Existing guards to copy: `components/{team,content,agents,payments,events,campaigns,sponsorship}/tests/integration/test_*query_count.py`.

## 2. Signal bridges MUST select_related on `pk_set` queries

M2M `post_add` / `post_remove` handlers that loop over `Model.objects.filter(pk__in=pk_set)` and call a service per row MUST eager-load whatever the service accesses. Bulk M2M linking (e.g. adding 50 donations to an event) otherwise fires 50 × N FK queries in a single transaction.

```python
# CORRECT
donations = Donation.objects.filter(pk__in=pk_set).select_related(
    "workspace", "recipient", "transaction", "budget",
)
for donation in donations:
    sync_campaign_income_transaction(campaign, donation)

# WRONG — 50 donations × 4 FK reads in sync_*() = 200 extra queries
for donation in Donation.objects.filter(pk__in=pk_set):
    sync_campaign_income_transaction(campaign, donation)
```

**Reference:** `components/sponsorship/infrastructure/adapters/django_{event,campaign}_donation_signal_bridge.py::_handle_add`.

## 3. Never `.exists()` followed by `.filter()`-and-iterate

`exists()` runs its own query. If followed by the same filter in a loop, you've paid for two queries when one would do. Only use `.exists()` when you genuinely want a boolean and will discard the rows.

```python
# CORRECT
transactions = list(Transaction.active.filter(workspace=ws).select_related("recipient"))
if transactions:
    for tx in transactions:
        ...

# WRONG — 2 round-trips when 1 suffices
if Transaction.active.filter(workspace=ws).exists():
    for tx in Transaction.active.filter(workspace=ws):
        ...
```

## 4. Use active managers, never `.filter(is_deleted=False)`

Soft-deleted models expose `.active` managers. Use them consistently. `.objects.filter(is_deleted=False)` bitrots when the soft-delete model evolves (e.g. adding a tombstone state).

```python
# CORRECT
Transaction.active.filter(workspace=ws)
Budget.active.current_workspace(ws_id)

# WRONG
Transaction.objects.filter(is_deleted=False, workspace=ws)
```

## 5. Background tasks iterate with `chunk_size`

A Celery task that processes every transaction / donation / row-of-something MUST use `.iterator(chunk_size=500)`. Without it, Django materialises the entire result set into memory — fine at dev volumes, OOM at prod.

```python
# CORRECT
donations = Donation.objects.filter(recipient__isnull=False).select_related(
    "recipient", "workspace", "transaction"
)
for donation in donations.iterator(chunk_size=500):
    sync_recipient_ledger_from_donation(donation)

# WRONG — loads everything into RAM
for donation in Donation.objects.filter(recipient__isnull=False):
    sync_recipient_ledger_from_donation(donation)
```

Chunk size trades memory against round-trips. 500 is a reasonable default.

## 6. Indexes must match the filter + order-by combination

Django composite indexes are column-ordered. `(workspace, date)` supports `filter(workspace=X).order_by("-date")` but NOT `filter(date__gte=X)` alone (prefix rule). Before adding an index, check if the column combination is already covered — duplicate indexes slow writes.

**Before adding a new index:**

1. Read `Meta.indexes` on the target model.
2. Check whether the filter you're adding is a prefix of an existing index.
3. If a prefix match exists, you're done.
4. If not, pick an index that covers WHERE + ORDER BY, put the most-selective column first.

```python
# Existing Transaction.Meta.indexes
#   (workspace, date)                       ← covers .filter(workspace).order_by("-date")
#   (workspace, status, date)               ← covers .filter(workspace, status).order_by("-date")
#   (workspace, transaction_type, date)
#   (workspace, source_type, date)
#   (provider, external_id)                 ← idempotency lookups
```

A new `.filter(workspace=X, recipient=Y).order_by("-date")` is NOT covered — the existing `(workspace, date)` index scans dates then filters recipient in Python. Adding `(workspace, recipient, date)` would help; confirm it's hot before adding.

## 7. Use Celery for anything >100ms

HTTP handlers block the WSGI worker until they return. Anything that calls Stripe, sends email, generates a PDF, computes embeddings, or iterates over many rows MUST be offloaded to Celery.

```python
# CORRECT — controller enqueues, returns 202, work happens async
class DonationCheckoutController(APIView):
    def post(self, request, workspace_id):
        order = self._use_case.execute(...)
        send_donation_notification.delay(notification_id=str(order.notification_id))
        return Response(OrderResource.from_result(order), status=202)

# WRONG — synchronous Stripe + email call in the request path
class DonationCheckoutController(APIView):
    def post(self, request, workspace_id):
        charge = stripe.Charge.create(...)          # 500–1500ms
        send_mail("Thanks", ..., [request.user.email])  # 200–800ms
        return Response(...)                         # user waits ~2s
```

Invoke the `celery-tasks` skill for the full reliability playbook (idempotency, retries, lossless deploys, dispatch-after-commit, monitoring, queues); its §0 carries the three hardest-to-remember invariants (pass IDs not objects, lossless-deploy settings, dispatch after commit).

## 8. Caching — when, and when not

**Cache when:**
- Data is read far more than written (feature flags, currencies, workspace metadata).
- Data has an explicit TTL (token refresh, rate limits).
- Computation is provably expensive, not just repeated.

**Do NOT cache when:**
- Invalidation is non-trivial or error-prone.
- A stale value could corrupt state or lose data.
- A missing `select_related()` would make the problem disappear.

**Cache layers:**

| Layer | Purpose | Reference |
|---|---|---|
| Per-request dict on `request` | Avoid re-querying the same row twice in one request | `components/shared_platform/infrastructure/services/feature_flags.py::_request_cache` |
| `django.core.cache` (Redis-backed) | Shared cache across workers, TTL'd | `FEATURE_FLAGS_VERSION_CACHE_KEY` pattern |
| `bump_feature_flags_version()` | O(1) global invalidation by versioning cache keys | `components/shared_platform/infrastructure/services/feature_flags.py::bump_feature_flags_version` |

Before caching, verify it's actually slow — not just repeated. Often a repository `select_related()` fixes the pain without adding cache-invalidation debt.

## 9. `SerializerMethodField` that runs ORM queries is a smell

If a `SerializerMethodField` reads more data than what's on the entity, move that data into the base queryset via `annotate()` or `select_related()`. Method fields run once per row.

```python
# WRONG — runs 1 query per row
def get_transaction_count(self, obj) -> int:
    return obj.transactions.count()

# CORRECT — annotate once in the repository
class WorkspaceRepository:
    def list_with_counts(self):
        return Workspace.active.annotate(transaction_count=Count("transactions"))

# In serializer
transaction_count = serializers.IntegerField(read_only=True)
```

## 10. Never raw SQL outside management commands

Raw SQL bypasses the ORM's query tracking, `select_related` resolution, and tenant routing. Acceptable in schema management commands (backfills, index creation). Everywhere else, use the ORM.

```python
# WRONG — in a repository or service
with connection.cursor() as cursor:
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE ...")

# CORRECT
Transaction.active.filter(workspace=ws).aggregate(total=Sum("amount"))["total"]
```

## 11. Pagination is not optional for list endpoints

Every list endpoint MUST paginate. DRF's `PageNumberPagination` (9/page default) is wired globally. Don't bypass it. Don't write `Model.objects.all()` into a serializer's `many=True` call.

```python
# CORRECT — DRF paginates automatically
class TransactionList(generics.ListAPIView):
    serializer_class = TransactionGetSerializer
    def get_queryset(self):
        return TransactionReadRepository().list_transactions(self._build_query())

# WRONG — dumps the entire table to the client
class TransactionList(APIView):
    def get(self, request):
        return Response(TransactionGetSerializer(Transaction.active.all(), many=True).data)
```

---

# Diagnosing performance issues

## Finding N+1s locally

No APM / Datadog. Django logs every SQL query when `DEBUG=True`.

1. Start the stack: `make up`.
2. Hit the suspect endpoint from frontend or curl.
3. Count queries:
   ```bash
   make logs-web | grep -E "(SELECT|INSERT|UPDATE|DELETE) " | wc -l
   ```
4. If the count is disproportionate to the page (50+ queries for a 9-row list), find repeats:
   ```bash
   make logs-web | grep -E "^\(" | sort | uniq -c | sort -rn | head
   ```
5. Any query appearing `N+` times for an `N`-row list is an N+1. Trace it to the serializer field, fix in the repository.

## Diagnosing in a Python shell

For a targeted check during development:

```python
from django.db import connection, reset_queries
from django.conf import settings
settings.DEBUG = True  # required for connection.queries to populate

reset_queries()
list(my_repository.list_things()[:10])
print(f"queries: {len(connection.queries)}")
```

Rule of thumb for a paginated list endpoint: **≤ 5 queries total** is healthy (1 count + 1 main + a few `prefetch_related`). > 20 queries for a single page is a bug.

## Before concluding "the DB is the bottleneck"

Checklist:

1. Is `select_related` missing for an FK the serializer reads?
2. Is `prefetch_related` missing for a reverse FK / M2M?
3. Is the serializer calling `obj.related_set.count()` in a loop? Use `annotate(Count(...))`.
4. Is a `SerializerMethodField` running an ORM query?
5. Is there an `ORDER BY` that isn't index-backed?

If all five are clean and the endpoint is still slow, the bottleneck is elsewhere — external service, Python-side computation, or serialization. Profile with `cProfile` or install `django-debug-toolbar` / `django-silk` in dev settings.

## What we do NOT have (yet)

- **Automatic eager-loading** (Themis uses `jit_preloader`). Python has no equivalent; we do it manually in repositories. Stay disciplined — that's what this rule is for.
- **Read replicas.** Single-DB. Revisit if read load becomes the bottleneck.
- **APM / query monitoring** (Datadog spans). Rely on log grep + `connection.queries` for now.
