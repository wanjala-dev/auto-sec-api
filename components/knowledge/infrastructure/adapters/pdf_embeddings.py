"""
PDF Embeddings Module - Handle PDF text extraction and embedding generation
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# LangChain imports (community modules for v0.2+ compatibility)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader

# AI imports
from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory

# Per-document indexing cap. Indexing is opt-in and metered per workspace,
# but a single 2,000-page upload could still monopolise a worker slot and
# flood the vector table with low-value chunks — retrieval quality DROPS
# as noise grows. Beyond the cap the tail pages are skipped and the result
# says so, so the UI can tell the user what was indexed.
MAX_EMBED_PAGES = 300


def create_embeddings_for_pdf(
    pdf_id: str, pdf_path: str, user_id: str = None, workspace_id: str = None
) -> dict[str, Any]:
    """
    Generate and store embeddings for the given PDF

    1. Extract text from the specified PDF.
    2. Divide the extracted text into manageable chunks.
    3. Generate an embedding for each chunk.
    4. Persist the generated embeddings.

    Args:
        pdf_id: The unique identifier for the PDF.
        pdf_path: The file path to the PDF.
        user_id: The ID of the user who owns this PDF.
        workspace_id: The ID of the workspace this PDF belongs to.

    Returns:
        Dictionary with processing results

    Example Usage:
        result = create_embeddings_for_pdf('123456', '/path/to/pdf', user_id='user123', workspace_id='seed456')

    Chat System Usage:
        # When building chat, filter documents by user and workspace:
        # vector_store.similarity_search(
        #     query="your question",
        #     filter={"user_id": "user123", "workspace_id": "seed456", "type": "pdf"}
        # )
    """
    logger.info(f"🚀 Starting PDF embeddings creation for file {pdf_id}: {pdf_path}")

    try:
        # Step 1: Create text splitter
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)

        # Step 2: Load pages, apply the per-document cap, then split
        logger.info(f"📄 Loading and splitting PDF {pdf_id}")
        loader = PyPDFLoader(pdf_path)
        pages = loader.load()
        total_pages = len(pages)
        truncated = total_pages > MAX_EMBED_PAGES
        if truncated:
            logger.warning(
                "pdf_index_truncated pdf_id=%s total_pages=%s indexed_pages=%s",
                pdf_id,
                total_pages,
                MAX_EMBED_PAGES,
            )
            pages = pages[:MAX_EMBED_PAGES]
        docs = text_splitter.split_documents(pages)

        logger.info(f"✅ Created {len(docs)} document chunks for PDF {pdf_id}")

        # Step 3: Add metadata to each document
        from django.utils import timezone

        current_time = timezone.now().isoformat()

        for doc in docs:
            doc.metadata = {
                "page": doc.metadata.get("page", 0),
                "text": doc.page_content,
                "pdf_id": pdf_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "type": "pdf",
                "status": "active",
                "created_at": current_time,
                "privacy": "private",  # PDFs are typically private
            }

        # Step 4: Store chunks where agent retrieval actually reads them.
        logger.info(f"💾 Storing documents in vector store for PDF {pdf_id}")
        # Route through the EmbeddingChunk-backed indexer so PdfChatUseCase's
        # pgvector retrieval (has_indexed_content + search over ai_embedding_chunks)
        # finds this PDF. The old VectorStoreFactory path wrote to LangChain
        # PGVector's OWN tables (langchain_pg_embedding), which the retrieval
        # adapter never reads — so every PDF chat returned "No content found"
        # (store-split fix 2026-07-15).
        from components.knowledge.infrastructure.adapters.pgvector_document_indexer import (
            index_documents,
        )

        index_documents(docs)

        logger.info(f"✅ Successfully stored {len(docs)} documents for PDF {pdf_id}")

        # Return success results
        result = {
            "success": True,
            "pdf_id": pdf_id,
            "pdf_path": pdf_path,
            "chunks_created": len(docs),
            "embeddings_generated": len(docs),
            "chunk_size": 500,
            "chunk_overlap": 100,
            "total_pages": total_pages,
            "pages_indexed": len(pages),
            "truncated": truncated,
        }

        logger.info(f"🎉 Successfully completed PDF embeddings for file {pdf_id}")
        return result

    except Exception as e:
        error_msg = f"Error creating PDF embeddings for {pdf_id}: {e!s}"
        logger.error(error_msg)
        return {"success": False, "pdf_id": pdf_id, "pdf_path": pdf_path, "error": error_msg}


def get_pdf_embeddings_status() -> dict[str, Any]:
    """
    Get the status of PDF processing libraries

    Returns:
        Dictionary with library availability status
    """
    return {
        "langchain_available": True,  # We're using direct imports now
        "embeddings_providers": EmbeddingsFactory.get_available_providers(),
    }
