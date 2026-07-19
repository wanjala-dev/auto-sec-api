"""Prompt builder for embedding-based Q&A."""

from typing import List


def build_embeddings_response(
    *,
    query: str,
    context_content: List[str],
    workspace_name: str = "this workspace",
) -> str:
    """Compose a prompt for answering questions based on retrieved context."""
    context_text = "\n\n".join(context_content)
    return (
        f"Based on the following information about {workspace_name}, please answer the user's question: \"{query}\"\n\n"
        f"Context about the workspace:\n{context_text}\n\n"
        "Please provide a helpful, conversational response based on this information. "
        "If the context doesn't contain enough information to answer the question, say so politely and suggest they try one of the specific commands like \"summary of this workspace\" or \"create a budget\"."
    )
