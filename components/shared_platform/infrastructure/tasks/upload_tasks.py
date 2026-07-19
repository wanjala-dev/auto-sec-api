"""
Celery tasks for file processing and embedding generation
"""

import logging
import os
import tempfile
from contextlib import contextmanager

from celery import shared_task
from django.utils import timezone

from components.knowledge.infrastructure.adapters.document_embeddings import create_embeddings_for_document

# AI imports
from components.knowledge.infrastructure.adapters.pdf_embeddings import create_embeddings_for_pdf

logger = logging.getLogger(__name__)


def _build_retryable_exceptions() -> tuple[type[BaseException], ...]:
    """Transient failure classes worth a backed-off retry (celery-tasks §3a).

    Everything else — ``ValueError`` from an unprocessable file, programming
    errors — fails fast instead of burning retries on a doomed pipeline.
    """
    from django.db.utils import InterfaceError, OperationalError

    candidates: list[type[BaseException]] = [
        TimeoutError,
        ConnectionError,
        OperationalError,
        InterfaceError,
    ]
    try:  # OpenAI transient errors (timeouts / rate limits / connection drops)
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
    except Exception:  # pragma: no cover - openai always present in prod
        pass
    return tuple(dict.fromkeys(candidates))


_RETRYABLE_EXC = _build_retryable_exceptions()


def _embeddings_configured() -> bool:
    """Return True when embeddings providers are configured."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    return bool(os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_API_BASE"))


def _mark_embedding_skipped(file_instance, error: Exception) -> None:
    """Embeddings unavailable in this environment — the document is NOT
    indexed and must not read as if it were. It returns to not_indexed
    (with the reason recorded) so the UI offers Index again once the
    environment is configured. Pre-2026-07 this marked ``completed``,
    which made un-indexed docs look groundable."""
    file_instance.processing_status = "not_indexed"
    file_instance.processing_error = f"Embeddings skipped: {error}"
    file_instance.processed_at = timezone.now()
    file_instance.save(update_fields=["processing_status", "processing_error", "processed_at"])


def _mark_indexing_failed(file_instance, error: Exception) -> None:
    """Terminal indexing failure (bad file, exhausted retries): status is
    failed — visibly retryable — never a silent ``completed``."""
    file_instance.processing_status = "failed"
    file_instance.processing_error = str(error)
    file_instance.processed_at = timezone.now()
    file_instance.save(update_fields=["processing_status", "processing_error", "processed_at"])


@contextmanager
def _local_file_path(file_instance):
    """Yield a LOCAL filesystem path for the file's bytes.

    The embedding loaders (PyPDFLoader etc.) need a real path. Local
    storage exposes ``FieldFile.path``; remote storage (S3MediaStorage on
    prod — where presigned uploads land) raises ``NotImplementedError`` for
    it, which silently failed every embed-on-upload in prod. For remote
    storage, stream the object into a NamedTemporaryFile (extension
    preserved so loaders detect the format) and clean it up afterwards.
    """
    storage_file = file_instance.file
    try:
        path = storage_file.path
    except (NotImplementedError, ValueError):
        path = None
    if path and os.path.exists(path):
        yield path
        return

    suffix = os.path.splitext(storage_file.name or "")[1] or ""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        storage_file.open("rb")
        try:
            for chunk in storage_file.chunks():
                tmp.write(chunk)
        finally:
            storage_file.close()
        tmp.close()
        yield tmp.name
    finally:
        if not tmp.closed:
            tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:  # already gone — nothing to clean up
            pass


@shared_task(
    bind=True,
    max_retries=3,
    name="infrastructure.uploads.tasks.process_pdf_file",
    soft_time_limit=480,
    time_limit=600,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_pdf_file(self, file_id):
    """
    Process a PDF file and generate embeddings

    Args:
        file_id: ID of the File model instance

    Returns:
        dict: Processing result
    """
    from infrastructure.persistence.uploads.models import File

    logger.info("process_pdf_file started file_id=%s task_id=%s", file_id, self.request.id)

    try:
        file_instance = File.objects.get(id=file_id)

        if not _embeddings_configured():
            _mark_embedding_skipped(file_instance, "AI embeddings are not configured.")
            logger.warning("Embeddings skipped for PDF %s: AI not configured", file_id)
            return {"success": True, "file_id": file_id, "skipped": True, "reason": "AI not configured"}

        file_instance.processing_status = "processing"
        file_instance.save()

        logger.info("process_pdf_file embedding file_id=%s name=%s", file_id, file_instance.file.name)

        # Call the comprehensive PDF embeddings function. _local_file_path
        # materializes S3-stored bytes (presigned uploads) to a temp file —
        # PyPDFLoader needs a real filesystem path.
        with _local_file_path(file_instance) as pdf_path:
            embeddings_result = create_embeddings_for_pdf(
                pdf_id=str(file_id),
                pdf_path=pdf_path,
                user_id=str(file_instance.owner.id) if file_instance.owner else None,
                workspace_id=str(file_instance.workspace_id) if file_instance.workspace_id else None,
            )

        if not embeddings_result["success"]:
            raise ValueError(f"Failed to process PDF: {embeddings_result['error']}")

        # Update file instance with extracted text and metadata
        file_instance.pdf_text = "Text extracted and processed"
        file_instance.pdf_page_count = embeddings_result.get("total_pages") or 1
        if embeddings_result.get("truncated"):
            # Surface the per-document cap so the UI can say what was indexed.
            insights = dict(file_instance.ai_insights or {})
            insights["indexing"] = {
                "truncated": True,
                "pages_indexed": embeddings_result.get("pages_indexed"),
                "total_pages": embeddings_result.get("total_pages"),
            }
            file_instance.ai_insights = insights
        file_instance.processing_status = "completed"
        file_instance.processed_at = timezone.now()
        file_instance.processing_error = None
        if not file_instance.source or file_instance.source == "manual_upload":
            file_instance.source = "knowledge_base"
        file_instance.save()

        # Extract AI insights from the indexed chunks
        _extract_file_insights.delay(file_id, str(file_id))

        logger.info(
            "process_pdf_file completed file_id=%s embeddings=%s",
            file_id,
            embeddings_result["embeddings_generated"],
        )

        return {
            "success": True,
            "file_id": file_id,
            "chunks_created": embeddings_result["chunks_created"],
            "embeddings_generated": embeddings_result["embeddings_generated"],
            "chunk_size": embeddings_result["chunk_size"],
            "chunk_overlap": embeddings_result["chunk_overlap"],
        }

    except File.DoesNotExist:
        logger.warning("process_pdf_file: file %s not found", file_id)
        return {"success": False, "error": "File not found"}

    except Exception as exc:
        logger.exception("process_pdf_file failed file_id=%s", file_id)

        # Record the error on the row (best-effort).
        try:
            file_instance = File.objects.get(id=file_id)
            file_instance.processing_error = str(exc)
            file_instance.save(update_fields=["processing_error"])
        except File.DoesNotExist:
            logger.warning("process_pdf_file: file %s vanished during error handling", file_id)
        except Exception:
            logger.exception("process_pdf_file: failed to record error file_id=%s", file_id)

        # celery-tasks §3a: only transient failures are worth retrying. An
        # unprocessable-PDF ValueError or a programming error will never succeed
        # on retry — retrying just re-embeds the same doc and wastes worker
        # slots. §3b: self.retry honours the decorator's backoff + jitter (no
        # hand-rolled lockstep countdown).
        if isinstance(exc, _RETRYABLE_EXC) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc

        try:
            file_instance = File.objects.get(id=file_id)
            _mark_indexing_failed(file_instance, exc)
        except File.DoesNotExist:
            pass

        return {"success": False, "file_id": file_id, "error": str(exc)}


@shared_task(
    name="infrastructure.uploads.tasks.process_pending_pdfs",
    soft_time_limit=480,
    time_limit=600,
)
def process_pending_pdfs():
    """
    Process all pending PDF files
    This can be run as a periodic task to catch any files that weren't processed
    """
    from infrastructure.persistence.uploads.models import File

    pending_pdfs = File.objects.filter(file_type="pdf", processing_status="pending")

    results = []
    for pdf_file in pending_pdfs:
        logger.info(f"Processing pending PDF: {pdf_file.id}")
        result = process_pdf_file.delay(pdf_file.id)
        results.append({"file_id": pdf_file.id, "task_id": result.id})

    return {"success": True, "processed_count": len(results), "results": results}


@shared_task(
    bind=True,
    max_retries=3,
    name="infrastructure.uploads.tasks.process_document_file",
    soft_time_limit=480,
    time_limit=600,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_document_file(self, file_id):
    """
    Process a non-PDF document (doc, docx, csv, xls/xlsx) and generate embeddings.
    """
    from infrastructure.persistence.uploads.models import File

    try:
        file_instance = File.objects.get(id=file_id)

        if not file_instance.is_document:
            logger.error("File %s is not a supported document", file_id)
            return {"success": False, "error": "File is not a supported document"}

        if not _embeddings_configured():
            _mark_embedding_skipped(file_instance, "AI embeddings are not configured.")
            logger.warning("Embeddings skipped for document %s: AI not configured", file_id)
            return {"success": True, "file_id": file_id, "skipped": True, "reason": "AI not configured"}

        file_instance.processing_status = "processing"
        file_instance.save()

        logger.info("Starting document processing for file %s: %s", file_id, file_instance.file.name)

        # _local_file_path materializes S3-stored bytes (presigned uploads)
        # to a temp file — the document loaders need a real filesystem path.
        with _local_file_path(file_instance) as file_path:
            embeddings_result = create_embeddings_for_document(
                file_id=str(file_id),
                file_path=file_path,
                user_id=str(file_instance.owner.id) if file_instance.owner else None,
                workspace_id=str(file_instance.workspace_id) if file_instance.workspace_id else None,
            )

        if not embeddings_result["success"]:
            raise ValueError(f"Failed to process document: {embeddings_result['error']}")

        file_instance.processing_status = "completed"
        file_instance.processed_at = timezone.now()
        file_instance.processing_error = None
        if not file_instance.source or file_instance.source == "manual_upload":
            file_instance.source = "knowledge_base"
        file_instance.save()

        # Extract AI insights from the indexed chunks
        _extract_file_insights.delay(file_id, str(file_id))

        logger.info(
            "Successfully processed document %s. Generated %s embeddings",
            file_id,
            embeddings_result["embeddings_generated"],
        )

        return {
            "success": True,
            "file_id": file_id,
            "chunks_created": embeddings_result["chunks_created"],
            "embeddings_generated": embeddings_result["embeddings_generated"],
            "chunk_size": embeddings_result["chunk_size"],
            "chunk_overlap": embeddings_result["chunk_overlap"],
        }

    except File.DoesNotExist:
        logger.warning("File %s not found for document processing", file_id)
        return {"success": False, "error": "File not found"}

    except Exception as exc:
        logger.exception("Error processing document %s", file_id)

        try:
            file_instance = File.objects.get(id=file_id)
            file_instance.processing_error = str(exc)
            file_instance.save(update_fields=["processing_error"])
        except File.DoesNotExist:
            logger.warning("File %s vanished while handling document error", file_id)
        except Exception:
            logger.exception("Error updating file status for %s", file_id)

        # §3a: retry only transient failures; §3b: backoff + jitter from the decorator.
        if isinstance(exc, _RETRYABLE_EXC) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc

        try:
            file_instance = File.objects.get(id=file_id)
            _mark_indexing_failed(file_instance, exc)
        except File.DoesNotExist:
            pass

        return {"success": False, "file_id": file_id, "error": str(exc)}


INSIGHTS_PROMPT = (
    "You are a document analysis assistant. Analyze the following document text and "
    "return a JSON object with these fields:\n"
    '- "summary": A 1-2 sentence summary of what this document is about\n'
    '- "document_type": The type of document (e.g. "bank_statement", "invoice", "budget", "report", "contract", "receipt", "letter", "other")\n'
    '- "highlights": A JSON array of 3-5 key insights, each with:\n'
    '  - "label": Short label (e.g. "Total Amount", "Date Range", "Key Finding")\n'
    '  - "value": The extracted value or insight\n'
    '  - "icon": One of: "dollar", "calendar", "tag", "grid", "check", "repeat", "alert", "info"\n\n'
    "Document text:\n{context}\n\n"
    "Return ONLY the JSON object, no explanation:"
)


@shared_task(
    name="infrastructure.uploads.tasks.extract_file_insights",
    bind=True,
    max_retries=2,
    soft_time_limit=120,
    time_limit=180,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def _extract_file_insights(self, file_id, pdf_id):
    """Extract AI insights from an indexed document's chunks.

    Runs after embeddings are created so it does not block the upload.
    """
    import json as json_mod

    from infrastructure.persistence.uploads.models import File

    try:
        file_instance = File.objects.get(id=file_id)

        from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import (
            create_elasticsearch_client,
        )

        es = create_elasticsearch_client()
        index_name = os.environ.get("ELASTICSEARCH_INDEX_NAME", "ai_documents")
        res = es.search(index=index_name, body={"size": 200, "query": {"term": {"metadata.pdf_id": str(pdf_id)}}})

        chunks = []
        for hit in res.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            text = src.get("text") or src.get("content") or src.get("page_content") or ""
            if text.strip():
                chunks.append(text)

        if not chunks:
            logger.info("No chunks found for file %s, skipping insights", file_id)
            return {"success": False, "reason": "no_chunks"}

        context = "\n\n".join(chunks)[:12000]

        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

        llm = LLMFactory.create_llm(
            provider="openai",
            model_name="gpt-4o-mini",
            temperature=0.1,
            max_tokens=1000,
        )

        prompt = INSIGHTS_PROMPT.format(context=context)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        cleaned = content.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            if first_nl > 0:
                cleaned = cleaned[first_nl + 1 :]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start < 0 or end <= start:
            logger.warning("LLM insights response not valid JSON for file %s", file_id)
            return {"success": False, "reason": "invalid_json"}

        insights_data = json_mod.loads(cleaned[start:end])

        from django.utils import timezone as tz

        file_instance.ai_insights = {
            "generated_at": tz.now().isoformat(),
            "model_used": "gpt-4o-mini",
            "summary": insights_data.get("summary", ""),
            "document_type": insights_data.get("document_type", "other"),
            "highlights": insights_data.get("highlights", []),
        }
        file_instance.save(update_fields=["ai_insights"])
        logger.info(
            "Extracted AI insights for file %s: %d highlights", file_id, len(insights_data.get("highlights", []))
        )
        return {"success": True, "file_id": file_id}

    except File.DoesNotExist:
        return {"success": False, "error": "file_not_found"}
    except Exception as exc:
        logger.exception("Insights extraction failed for file %s", file_id)
        # §3a/§3b: retry only transient ES/LLM failures, with the decorator's
        # backoff + jitter (was a fixed 30s countdown — synchronized herd).
        if isinstance(exc, _RETRYABLE_EXC) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc
        return {"success": False, "error": str(exc)[:200]}
