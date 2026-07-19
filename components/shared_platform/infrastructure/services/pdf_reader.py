"""Shared PDF reader utility — lives in the shared platform layer.

Extracts text from PDF files. Handles encrypted PDFs gracefully.
Reusable by any bounded context.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_content: bytes | str, file_path: str | None = None) -> str:
    """Extract all text from a PDF file.

    Tries multiple strategies:
    1. PyPDFLoader (LangChain) — handles most PDFs including some encrypted ones
    2. PyPDF2 with pycryptodome — for AES-encrypted PDFs
    3. Raw byte extraction — last resort

    Args:
        file_content: Raw PDF bytes (or path string for compatibility)
        file_path: Optional path if file is already on disk

    Returns:
        Extracted text as a single string
    """
    # Write to temp file if we only have bytes
    if file_path is None:
        if isinstance(file_content, str):
            file_path = file_content
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(file_content if isinstance(file_content, bytes) else file_content.encode())
            tmp.close()
            file_path = tmp.name

    text = ""

    # Strategy 1: LangChain PyPDFLoader
    try:
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        text = "\n\n".join(doc.page_content for doc in docs if doc.page_content)
        if text.strip():
            logger.info("PDF text extracted via PyPDFLoader (%d chars)", len(text))
            return text
    except Exception as exc:
        logger.debug("PyPDFLoader failed: %s", exc)

    # Strategy 2: PyPDF2 with password=""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        if reader.is_encrypted:
            reader.decrypt("")
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
        text = "\n\n".join(pages)
        if text.strip():
            logger.info("PDF text extracted via PyPDF2 (%d chars)", len(text))
            return text
    except Exception as exc:
        logger.debug("PyPDF2 failed: %s", exc)

    logger.warning("Could not extract text from PDF: %s", file_path)
    return text


def extract_tables_with_llm(
    text: str,
    *,
    table_type: str = "transactions",
    provider: str | None = None,
    model_name: str = "gpt-3.5-turbo",
) -> list[dict[str, Any]]:
    """Use LLM to parse table data from extracted PDF text.

    Args:
        text: Raw text extracted from PDF
        table_type: What kind of table to look for ("transactions", "expenses", "income")
        provider: LLM provider override
        model_name: Model to use

    Returns:
        List of dicts, each representing a row from the table
    """
    if not text or len(text.strip()) < 50:
        return []

    try:
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory
    except ImportError:
        logger.warning("LLMFactory not available — cannot parse PDF tables")
        return []

    import json as json_module
    import os as os_module

    resolved_provider = provider or (
        "openai" if os_module.environ.get("OPENAI_API_KEY") else "azure"
    )

    try:
        llm = LLMFactory.create_llm(
            provider=resolved_provider,
            model_name=model_name,
            temperature=0.1,
            max_tokens=2000,
        )
    except Exception as exc:
        logger.warning("Failed to create LLM for PDF parsing: %s", exc)
        return []

    prompt = (
        f"Extract all {table_type} from the following bank statement text. "
        f"Return ONLY a JSON array where each element has these fields:\n"
        f"- date (YYYY-MM-DD format)\n"
        f"- description (transaction description)\n"
        f"- amount (positive number, no currency symbol)\n"
        f"- category (your best guess: e.g. Food, Transport, Shopping, Bills, Transfer, etc.)\n"
        f"- type (\"debit\" or \"credit\")\n\n"
        f"Text:\n{text[:4000]}\n\n"
        f"Respond with ONLY the JSON array, no explanation."
    )

    try:
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            rows = json_module.loads(content[start:end])
            logger.info("LLM extracted %d transactions from PDF", len(rows))
            return rows
        else:
            logger.warning("LLM response did not contain JSON array")
            return []
    except Exception as exc:
        logger.warning("LLM PDF parsing failed: %s", exc)
        return []
