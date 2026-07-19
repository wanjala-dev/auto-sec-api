"""Celery tasks for the shared document import pipeline.

Each import runs asynchronously: upload → queue → parse → ready.
The task is retried up to 3 times on transient failures.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def _build_retryable_exceptions() -> tuple[type[BaseException], ...]:
    """Transient failure classes worth a backed-off retry (celery-tasks §3a).

    A parse/validation error or programming bug fails fast — retrying just
    re-runs the expensive RAG-index + OpenAI extraction on a doomed document.
    """
    from django.db.utils import InterfaceError, OperationalError

    candidates: list[type[BaseException]] = [
        TimeoutError,
        ConnectionError,
        OperationalError,
        InterfaceError,
    ]
    try:
        import openai

        candidates.extend(
            e
            for e in (
                getattr(openai, "APITimeoutError", None),
                getattr(openai, "APIConnectionError", None),
                getattr(openai, "RateLimitError", None),
                getattr(openai, "InternalServerError", None),
            )
            if isinstance(e, type)
        )
    except Exception:  # pragma: no cover
        pass
    return tuple(dict.fromkeys(candidates))


_RETRYABLE_EXC = _build_retryable_exceptions()

# ── Extraction prompts per import type ──────────────────────────
EXTRACTION_PROMPTS = {
    "expense": (
        "You are a financial data extraction assistant specialized in bank "
        "and credit-card statements. Extract ALL transaction line items "
        "from the document text below.\n\n"
        "CRITICAL RULES — bank/credit-card statements:\n"
        "1. The document usually carries a 'Statement period' line like "
        "'Dec 11, 2025 - Jan 10, 2026' near the top. Use it to infer the "
        "year for any short-form dates ('Dec. 12', 'Jan. 4') in the body.\n"
        "2. Classify every line into EXACTLY ONE of three types:\n"
        '   • "debit"    — a charge / expense the cardholder paid. The '
        "default for any line without a CR suffix or payment-style "
        "description.\n"
        '   • "transfer" — payments INTO the credit-card account that '
        "are NOT new revenue. Includes: 'TRSF FROM' / 'TRANSFER FROM "
        "ACCOUNT', 'PAYMENT - THANK YOU', 'AUTOPAY', 'BALANCE TRANSFER', "
        "'PRE-AUTHORIZED PAYMENT', any line that's a payment from a "
        "linked chequing/savings account. These zero out against the "
        "outflow on the other account and would fabricate phantom "
        "income if recorded.\n"
        '   • "credit"   — REAL inflows / negative expenses. Includes '
        "cashback rewards ('Cashback/Remises', 'CASHBACK CREDIT'), "
        "rebates ('Performance Card Rebate', 'CARD REBATE'), and "
        "merchant refunds (a returned charge to a vendor like 'AMAZON' "
        "where the amount has CR — this is a refund of a prior "
        "purchase).\n"
        "   When in doubt between 'transfer' and 'credit', prefer "
        "'transfer' — the cost of over-classifying as transfer is "
        "lower than fabricating income.\n"
        "3. Normalize merchant names. 'AMAZON* R06AS6593 VANCOUVER BC' "
        "→ 'Amazon'. 'PETRO-CANADA 92576 VANCOUVER BC' → 'Petro-Canada'. "
        "Strip city/state codes and merchant ID gibberish; keep the "
        "human-readable brand name. If you can't recover a brand, keep "
        "the cleaned-up original (trim whitespace, drop multi-space runs).\n"
        "4. Skip non-transaction artefacts: subtotals, interest charges "
        "lines that are summaries, page headers, footers, balance lines, "
        "rewards summary lines, and any row inside an 'Important "
        "Information' / boilerplate section.\n"
        "5. Treat 'Interest Purchases', 'Interest Charges', 'Annual Fee' "
        "as debits (real expenses you paid the bank).\n\n"
        "OUTPUT — return ONLY a JSON array. Each element MUST have:\n"
        '- "date" (YYYY-MM-DD, year inferred from statement period if '
        "needed; null only if you truly cannot determine it)\n"
        '- "description" (normalized merchant / description)\n'
        '- "amount" (positive number, no currency symbol, no thousands '
        "separators)\n"
        '- "category" (best guess from: Groceries, Restaurants, Transport, '
        "Fuel, Travel, Utilities, Subscriptions, Entertainment, "
        "Healthcare, Insurance, Education, Rent, Mortgage, Shopping, "
        "Personal Care, Pet, Charity, Salary, Interest, Bank Fee, "
        "Rewards, Refund, Transfer, Other)\n"
        '- "type" (one of "debit", "credit", "transfer" per the '
        "rules above)\n\n"
        "Document text:\n{context}\n\n"
        "JSON array only, no explanation, no markdown fences:"
    ),
    "income": (
        "You are a financial data extraction assistant. "
        "Extract ALL income/revenue line items from the following document text. "
        "Return ONLY a JSON array where each element has:\n"
        '- "date" (YYYY-MM-DD if available, otherwise null)\n'
        '- "description" (income source description)\n'
        '- "amount" (positive number, no currency symbol)\n'
        '- "category" (best guess: Donation, Grant, Sponsorship, Sales, Subscription, Refund, etc.)\n'
        '- "source" (name of payer/donor if available, otherwise null)\n\n'
        "Document text:\n{context}\n\n"
        "JSON array only, no explanation:"
    ),
    "budget": (
        "You are a budget planning assistant. "
        "Extract ALL budget line items from the following document text. "
        "Return ONLY a JSON array where each element has:\n"
        '- "description" (item name)\n'
        '- "amount" (planned amount as positive number, no currency symbol)\n'
        '- "category" (best guess: Food, Salary, Supplies, Utilities, Rent, Transport, etc.)\n\n'
        "Document text:\n{context}\n\n"
        "JSON array only, no explanation:"
    ),
    "recipient": (
        "You are a data extraction assistant. "
        "Extract ALL people/beneficiary records from the following document text. "
        "Return ONLY a JSON array where each element has:\n"
        '- "first_name" (given name)\n'
        '- "middle_name" (middle name, if available, otherwise null)\n'
        '- "last_name" (family name / surname, if available, otherwise null)\n'
        '- "age" (integer if available, otherwise null)\n'
        '- "date_of_birth" (YYYY-MM-DD or the raw string, otherwise null)\n'
        '- "gender" ("male", "female", or "other"; null if unknown)\n'
        '- "location" (address / city / region, otherwise null)\n'
        '- "photo_url" (link to a photo — often a Google Drive share URL, otherwise null)\n'
        '- "story" (longer biographical/background text, otherwise null)\n'
        '- "notes" (anything that doesn\'t fit the fields above)\n\n'
        "Preserve the original text from the document — do not paraphrase stories.\n\n"
        "Document text:\n{context}\n\n"
        "JSON array only, no explanation:"
    ),
    "donation": (
        "You are a financial data extraction assistant. "
        "Extract ALL donation records from the following document text. "
        "Return ONLY a JSON array where each element has:\n"
        '- "date" (YYYY-MM-DD if available, otherwise null)\n'
        '- "donor_name" (name of the donor)\n'
        '- "amount" (positive number, no currency symbol)\n'
        '- "method" (payment method if available: card, bank, cash, etc.)\n'
        '- "notes" (any additional context)\n\n'
        "Document text:\n{context}\n\n"
        "JSON array only, no explanation:"
    ),
    "contact": (
        "You are a CRM data extraction assistant. "
        "Extract ALL people/organization contact records from the following "
        "document text. Return ONLY a JSON array where each element has:\n"
        '- "first_name" (given name, otherwise null)\n'
        '- "last_name" (family name / surname, otherwise null)\n'
        '- "name" (full name or organization name if not split, otherwise null)\n'
        '- "email" (email address, otherwise null)\n'
        '- "phone" (phone number, otherwise null)\n'
        '- "city" (city, otherwise null)\n'
        '- "country" (2-letter country code or country name, otherwise null)\n'
        '- "role" (one of donor, sponsor, recipient, subscriber, funder, '
        "volunteer, board_member, prospect — otherwise null)\n"
        '- "tags" (comma-separated labels, otherwise null)\n'
        '- "notes" (anything else)\n\n'
        "Document text:\n{context}\n\n"
        "JSON array only, no explanation:"
    ),
}

# Search queries per import type (for RAG retrieval)
SEARCH_QUERIES = {
    "expense": "transactions payments debit credit amount date balance expense",
    "income": "income revenue donation grant payment received credit",
    "budget": "budget items planned expenses estimates salary costs",
    "recipient": "names people beneficiaries children students members",
    "donation": "donations gifts contributions pledges donors supporters",
    "contact": "contacts people donors supporters email phone name organization",
}

# Fallback prompt for types not in the map
DEFAULT_PROMPT = (
    "Extract ALL structured records from the following document text. "
    "Return ONLY a JSON array where each element has:\n"
    '- "description" (item description)\n'
    '- "amount" (number if applicable, otherwise null)\n'
    '- "date" (YYYY-MM-DD if applicable, otherwise null)\n'
    '- "category" (best guess category)\n'
    '- "notes" (any additional context)\n\n'
    "Document text:\n{context}\n\n"
    "JSON array only, no explanation:"
)


def _detect_format(filename: str) -> str:
    """Map file extension to format constant."""
    ext_map = {
        ".csv": "csv",
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "doc",
        ".xlsx": "xlsx",
        ".xls": "xls",
        ".json": "json",
        ".txt": "txt",
    }
    ext = os.path.splitext(filename or "")[1].lower()
    return ext_map.get(ext, "unknown")


def _parse_date(raw: str | None) -> date | None:
    if not raw or raw == "null":
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(raw), fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw) -> Decimal | None:
    if raw is None:
        return None
    try:
        return abs(Decimal(str(raw).replace(",", "").replace("$", "").strip()))
    except (InvalidOperation, ValueError):
        return None


@shared_task(
    name="document_import_parse",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=480,
    time_limit=600,
)
def document_import_parse(self, import_id: int):
    """Process a single DocumentImport asynchronously.

    1. Read file from storage
    2. Index via RAG pipeline (chunks → embeddings → ES)
    3. Retrieve all chunks
    4. Extract structured rows via LLM
    5. Create DocumentImportRow records
    6. Update status to ready / needs_review / failed
    """
    from infrastructure.persistence.imports.models import (
        DocumentImport,
        DocumentImportRow,
    )

    try:
        doc_import = DocumentImport.objects.get(pk=import_id)
    except DocumentImport.DoesNotExist:
        logger.error("DocumentImport %s not found", import_id)
        return {"error": "not_found"}

    # Mark as parsing + heartbeat so the watchdog can distinguish a truly
    # stuck import from a slow-but-alive one.
    doc_import.status = DocumentImport.STATUS_PARSING
    doc_import.last_heartbeat_at = timezone.now()
    doc_import.save(update_fields=["status", "last_heartbeat_at", "updated_at"])

    def _beat():
        """Stamp ``last_heartbeat_at`` so the watchdog sees progress."""
        DocumentImport.objects.filter(pk=import_id).update(last_heartbeat_at=timezone.now())

    try:
        # Read file content
        source_file = doc_import.source_file
        if not source_file or not source_file.file:
            raise ValueError("No source file attached to import")

        file_content = source_file.file.read()
        file_type = doc_import.source_format
        if file_type == "unknown":
            file_type = _detect_format(doc_import.original_filename)
            doc_import.source_format = file_type

        import_type = doc_import.import_type
        prompt = EXTRACTION_PROMPTS.get(import_type, DEFAULT_PROMPT)
        search_query = SEARCH_QUERIES.get(import_type, "data records items")

        # Use the shared DocumentProcessor
        from components.shared_platform.infrastructure.services.document_processor import (
            DocumentProcessor,
        )

        processor = DocumentProcessor()
        _beat()  # heartbeat: starting chunk-indexing + LLM extraction
        result = processor.process(
            file_content,
            file_type=file_type,
            extraction_prompt=prompt,
            workspace_id=str(doc_import.workspace_id),
            user_id=str(doc_import.uploaded_by_id or ""),
            search_query=search_query,
            max_chunks=200,
            llm_model="gpt-4o-mini",
            llm_max_tokens=4096,
        )
        _beat()  # heartbeat: LLM returned, building rows next

        if not result.success or not result.rows:
            doc_import.status = DocumentImport.STATUS_FAILED
            doc_import.error_message = " ".join(result.errors or ["No data extracted from document."])
            doc_import.summary = {
                "chunks_indexed": result.chunks_indexed,
                "chunks_retrieved": result.chunks_retrieved,
                "warnings": result.warnings,
            }
            doc_import.processed_at = timezone.now()
            doc_import.save(
                update_fields=[
                    "status",
                    "source_format",
                    "error_message",
                    "summary",
                    "processed_at",
                    "updated_at",
                ]
            )
            return {"status": "failed", "errors": result.errors}

        # Create rows — per-type validation rules. Money-shaped imports
        # (expense/income/donation/budget) need a positive amount to be
        # usable. People-shaped imports (recipient) need a name instead.
        rows_to_create = []
        valid_count = 0
        money_shaped = import_type in ("expense", "income", "donation", "budget")

        for i, raw_row in enumerate(result.rows):
            errors = []
            amount = _parse_amount(raw_row.get("amount"))
            parsed_date = _parse_date(raw_row.get("date"))

            # Compose a display label from whichever name-like fields
            # the LLM returned for this import type.
            name_parts = [
                raw_row.get("first_name"),
                raw_row.get("middle_name"),
                raw_row.get("last_name"),
            ]
            composed_name = " ".join(str(p).strip() for p in name_parts if p and str(p).strip())
            label = (
                raw_row.get("description") or raw_row.get("name") or raw_row.get("donor_name") or composed_name or ""
            ).strip()

            if money_shaped:
                if amount is None or amount <= 0:
                    errors.append("Invalid or missing amount")
            elif import_type == "recipient":
                # A recipient needs at least one name field — everything
                # else (age / gender / photo / story) is optional.
                if not label:
                    errors.append("Missing name")
            elif import_type == "contact" and not label and not (raw_row.get("email") or "").strip():
                # A contact needs at least a name OR an email (the dedup key);
                # everything else is optional.
                errors.append("Missing name and email")
            # For other import types, fall through — row counts as valid
            # as long as the LLM returned anything usable.

            category = (raw_row.get("category") or "").strip()
            row_type_raw = str(raw_row.get("type", "")).lower()
            # Three-way classification — see the prompt rules. Transfer
            # is the LLM's signal for "this is a payment INTO the credit
            # card from a linked chequing account; it's not new revenue".
            # The applier respects row_type=transfer and skips it
            # without creating a Transaction.
            if row_type_raw == "credit":
                row_type = "income"
            elif row_type_raw == "transfer":
                row_type = "transfer"
            else:
                row_type = "expense"

            is_valid = len(errors) == 0
            if is_valid:
                valid_count += 1

            rows_to_create.append(
                DocumentImportRow(
                    document_import=doc_import,
                    row_index=i,
                    label=label[:512],
                    amount=amount or Decimal("0"),
                    date=parsed_date,
                    category_name=category[:255],
                    row_type=row_type
                    if import_type in ("expense", "income")
                    # Recipient / donation / other imports keep the
                    # legacy 'other' bucket — they don't have an
                    # expense/income/transfer dimension.
                    else ("other"),
                    notes=raw_row.get("notes") or raw_row.get("source") or "",
                    parsed_data=raw_row,
                    raw_data=raw_row,
                    is_valid=is_valid,
                    validation_errors=errors,
                    status=DocumentImportRow.ROW_STATUS_PENDING,
                )
            )

        DocumentImportRow.objects.bulk_create(rows_to_create)

        # Update import status
        doc_import.row_count = len(rows_to_create)
        doc_import.valid_row_count = valid_count
        doc_import.status = DocumentImport.STATUS_READY if valid_count > 0 else DocumentImport.STATUS_NEEDS_REVIEW
        doc_import.summary = {
            "chunks_indexed": result.chunks_indexed,
            "chunks_retrieved": result.chunks_retrieved,
            "warnings": result.warnings,
        }
        doc_import.processed_at = timezone.now()
        doc_import.error_message = ""
        doc_import.save(
            update_fields=[
                "status",
                "source_format",
                "row_count",
                "valid_row_count",
                "summary",
                "processed_at",
                "error_message",
                "updated_at",
            ]
        )

        # Compute and save AI insights on the source file
        _compute_and_save_insights(doc_import, rows_to_create)

        # Send notification
        _notify_user(doc_import, valid_count)

        # Emit workflow event so bound workflows can trigger
        _emit_document_event(
            doc_import,
            "document_processed",
            {
                "import_id": doc_import.pk,
                "import_type": doc_import.import_type,
                "row_count": len(rows_to_create),
                "valid_count": valid_count,
                "filename": doc_import.original_filename,
            },
        )

        logger.info(
            "DocumentImport %s parsed: %d rows (%d valid)",
            import_id,
            len(rows_to_create),
            valid_count,
        )
        return {
            "status": doc_import.status,
            "row_count": len(rows_to_create),
            "valid_count": valid_count,
        }

    except Exception as exc:
        logger.exception("DocumentImport %s failed: %s", import_id, exc)
        doc_import.status = DocumentImport.STATUS_FAILED
        doc_import.error_message = str(exc)[:500]
        doc_import.processed_at = timezone.now()
        doc_import.save(
            update_fields=[
                "status",
                "error_message",
                "processed_at",
                "updated_at",
            ]
        )
        # celery-tasks §3a/§3b: retry ONLY transient errors (ES/OpenAI/DB
        # transport), with the decorator's backoff + jitter. A parse or
        # validation failure (e.g. unreadable source, bad extraction) will
        # never succeed on retry — re-running the RAG-index + LLM extraction
        # on it just burns load. Those fail fast (already marked FAILED above).
        if isinstance(exc, _RETRYABLE_EXC) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc
        return {"status": "failed", "error": str(exc)[:200]}


def _notify_user(doc_import, valid_count: int):
    """Notify the uploader when import processing completes.

    Historical bug: this used to call ``Notification.objects.create`` with
    ``title=``/``body=`` kwargs that don't exist on the model — the create
    raised ``TypeError`` on every run and the swallow-log below hid it, so
    import-complete notifications never fired. Routing through the dispatcher
    (with ``allow_self_notify`` — uploader is both actor and recipient) is the
    root fix.
    """
    try:
        from components.notifications.infrastructure.adapters.notification_service import (
            NotificationDispatcher,
        )
        from infrastructure.persistence.notifications.models import Notification
        from infrastructure.persistence.workspaces.models import Workspace

        if doc_import.uploaded_by is None:
            return
        workspace = Workspace.objects.filter(id=doc_import.workspace_id).first()
        filename = doc_import.original_filename or "your document"
        NotificationDispatcher().dispatch(
            actor=doc_import.uploaded_by,
            workspace=workspace,
            verb=(
                f"{doc_import.import_type.title()} import ready — "
                f"{valid_count} records extracted from {filename}. Review and approve them now."
            )[:255],
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[doc_import.uploaded_by],
            metadata={
                "kind": "document_import.completed",
                "import_id": str(doc_import.pk),
                "import_type": doc_import.import_type,
                "valid_count": valid_count,
                "filename": filename,
            },
            target=doc_import,
            allow_self_notify=True,
        )
    except Exception:
        logger.exception(
            "document_import_notify_failed import_id=%s uploaded_by_id=%s",
            doc_import.pk,
            doc_import.uploaded_by_id,
        )


def _emit_document_event(doc_import, trigger_type: str, payload: dict):
    """Emit a workflow event for document lifecycle transitions."""
    try:
        from components.workflow.infrastructure.adapters.dispatcher import (
            emit_workflow_event,
        )

        emit_workflow_event(
            workspace_id=str(doc_import.workspace_id),
            source_type="document",
            source_id=str(doc_import.pk),
            trigger_type=trigger_type,
            payload={
                "target_type": "contact",
                "target_id": str(doc_import.uploaded_by_id or ""),
                **payload,
            },
            idempotency_key=f"{trigger_type}-{doc_import.pk}",
        )
    except Exception as exc:
        logger.warning("Failed to emit workflow event %s: %s", trigger_type, exc)


# ── Source type mapping ─────────────────────────────────────
IMPORT_TYPE_TO_FILE_SOURCE = {
    "expense": "expense_import",
    "income": "income_import",
    "budget": "budget_import",
}


def _compute_and_save_insights(doc_import, rows):
    """Compute aggregate insights from extracted rows and save to File.ai_insights."""
    try:
        source_file = doc_import.source_file
        if not source_file:
            return

        from collections import Counter

        from django.utils import timezone as tz

        amounts = []
        categories = Counter()
        dates = []

        for row in rows:
            amt = row.amount
            if amt and amt > 0:
                amounts.append(float(amt))
            cat = row.category_name
            if cat:
                categories[cat] += 1
            if row.date:
                dates.append(row.date)

        total = sum(amounts)
        count = len(amounts)
        top_cats = categories.most_common(5)
        min_date = min(dates) if dates else None
        max_date = max(dates) if dates else None

        highlights = []

        # Total amount
        if count:
            import_type = doc_import.import_type
            label_map = {"expense": "Total spending", "income": "Total income", "budget": "Total budget"}
            highlights.append(
                {
                    "type": "total_amount",
                    "label": label_map.get(import_type, "Total"),
                    "value": f"${total:,.2f} across {count} {'items' if import_type == 'budget' else 'transactions'}",
                    "icon": "dollar",
                }
            )

        # Top categories
        if top_cats:
            top_name, top_count = top_cats[0]
            top_total = sum(float(r.amount) for r in rows if r.category_name == top_name and r.amount)
            highlights.append(
                {
                    "type": "top_category",
                    "label": "Top category",
                    "value": f"{top_name} (${top_total:,.2f})",
                    "icon": "tag",
                }
            )

        # Date range
        if min_date and max_date:
            highlights.append(
                {
                    "type": "date_range",
                    "label": "Period",
                    "value": f"{min_date.strftime('%b %d, %Y')} — {max_date.strftime('%b %d, %Y')}",
                    "icon": "calendar",
                }
            )

        # Category breakdown
        if len(top_cats) > 1:
            breakdown = ", ".join(f"{name} ({cnt})" for name, cnt in top_cats[:4])
            highlights.append(
                {
                    "type": "category_breakdown",
                    "label": "Categories",
                    "value": breakdown,
                    "icon": "grid",
                }
            )

        # Row count
        valid = sum(1 for r in rows if r.is_valid)
        invalid = len(rows) - valid
        if invalid:
            highlights.append(
                {
                    "type": "quality",
                    "label": "Data quality",
                    "value": f"{valid} valid, {invalid} need review",
                    "icon": "check",
                }
            )

        insights = {
            "generated_at": tz.now().isoformat(),
            "highlights": highlights,
            "document_category": doc_import.import_type,
            "source_import_id": doc_import.pk,
            "stats": {
                "total_amount": round(total, 2),
                "row_count": count,
                "category_count": len(categories),
                "top_categories": [{"name": n, "count": c} for n, c in top_cats],
            },
        }

        source_file.ai_insights = insights
        source_file.source = IMPORT_TYPE_TO_FILE_SOURCE.get(doc_import.import_type, "other")
        source_file.save(update_fields=["ai_insights", "source"])
        logger.info("Saved AI insights for file %s (%d highlights)", source_file.pk, len(highlights))
    except Exception as exc:
        logger.warning("Failed to compute insights for import %s: %s", doc_import.pk, exc)


# ── Watchdog: recover silently-dead imports ─────────────────────
# When a worker OOMs / restarts / hangs on an OpenAI call, the parse
# task dies without transitioning the import to a terminal state. The
# row sits in ``parsing`` forever and the frontend has nothing to
# retry against. This task runs on a Beat schedule and:
#   1. Re-enqueues imports that have a stale heartbeat (up to 2 auto-retries)
#   2. Marks hopelessly stuck imports as ``failed`` so the API can offer
#      a user-facing retry button.
# Heartbeat-based detection means long-running LLM calls that are
# still alive aren't mistakenly killed.
STUCK_HEARTBEAT_THRESHOLD_MINUTES = 15
MAX_AUTO_RETRIES = 2


@shared_task(name="sweep_stuck_document_imports")
def sweep_stuck_document_imports() -> dict:
    """Find DocumentImports stuck in active states and recover them.

    An import is considered stuck if its last heartbeat (or ``created_at``
    when no heartbeat exists) is older than the threshold AND status is
    ``pending``/``queued``/``parsing``.
    """
    from django.db.models import F, Q

    from infrastructure.persistence.imports.models import DocumentImport

    threshold = timezone.now() - timezone.timedelta(minutes=STUCK_HEARTBEAT_THRESHOLD_MINUTES)
    active_statuses = [
        DocumentImport.STATUS_PENDING,
        DocumentImport.STATUS_QUEUED,
        DocumentImport.STATUS_PARSING,
    ]
    # Heartbeat older than threshold, OR never beat and created longer ago.
    stuck = DocumentImport.objects.filter(
        status__in=active_statuses,
    ).filter(Q(last_heartbeat_at__lt=threshold) | Q(last_heartbeat_at__isnull=True, created_at__lt=threshold))

    retried = 0
    failed = 0
    for imp in stuck.iterator(chunk_size=100):
        if imp.retry_count < MAX_AUTO_RETRIES:
            DocumentImport.objects.filter(pk=imp.pk).update(
                status=DocumentImport.STATUS_PENDING,
                retry_count=F("retry_count") + 1,
                last_heartbeat_at=None,
                error_message="",
                updated_at=timezone.now(),
            )
            document_import_parse.delay(imp.pk)
            retried += 1
            logger.info(
                "stuck_import_retried import_id=%s retry_count=%s",
                imp.pk,
                imp.retry_count + 1,
            )
        else:
            DocumentImport.objects.filter(pk=imp.pk).update(
                status=DocumentImport.STATUS_FAILED,
                error_message=(
                    "Parse stalled — processing did not finish within "
                    f"{STUCK_HEARTBEAT_THRESHOLD_MINUTES} minutes on "
                    f"{MAX_AUTO_RETRIES} attempts. Please retry manually."
                ),
                processed_at=timezone.now(),
                updated_at=timezone.now(),
            )
            failed += 1
            logger.warning(
                "stuck_import_failed import_id=%s retry_count=%s",
                imp.pk,
                imp.retry_count,
            )

    if retried or failed:
        logger.info(
            "sweep_stuck_document_imports retried=%d failed=%d",
            retried,
            failed,
        )
    return {"retried": retried, "failed": failed}
