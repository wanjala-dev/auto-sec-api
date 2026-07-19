"""
Retrieval Chain Implementation
"""
# LangChain 1.x: legacy chains moved to the vendor-maintained langchain-classic package.
from langchain_classic.chains import ConversationalRetrievalChain
from .streamable import StreamableChain
from .traceable import TraceableChain
from typing import Optional


class StreamingConversationalRetrievalChain(
    TraceableChain, StreamableChain, ConversationalRetrievalChain
):
    """
    Conversational Retrieval Chain with streaming and tracing capabilities
    
    This combines:
    - ConversationalRetrievalChain: For question-answering with retrieval
    - StreamableChain: For streaming responses
    - TraceableChain: For monitoring and debugging
    """
    
    def __init__(self, *args, **kwargs):
        # Extract metadata and trace_id before passing to parent
        metadata = kwargs.pop('metadata', {})
        trace_id = kwargs.pop('trace_id', None)
        
        super().__init__(*args, **kwargs)
        
        # Set up tracing
        if trace_id:
            self.trace_id = trace_id
        self.metadata = metadata
    
    def stream_retrieval(self, question: str, chat_history: list = None, **kwargs):
        """
        Stream retrieval results
        
        Args:
            question: Question to ask
            chat_history: Previous conversation history
            **kwargs: Additional arguments
        
        Yields:
            Tokens as they are generated
        """
        input_data = {
            'question': question,
            'chat_history': chat_history or []
        }
        
        yield from self.stream(input_data, **kwargs)
    
    def get_retrieval_result(self, question: str, chat_history: list = None, **kwargs):
        """
        Get retrieval result without streaming
        
        Args:
            question: Question to ask
            chat_history: Previous conversation history
            **kwargs: Additional arguments
        
        Returns:
            Retrieval result
        """
        input_data = {
            'question': question,
            'chat_history': chat_history or []
        }
        
        return self(input_data, **kwargs)


# Utility helpers for retrieval flows
def normalize_metadata_value(v):
    """Normalize metadata values for consistent comparison (stringify or None)."""
    return str(v) if v is not None else None


def has_indexed_chunks(retriever, pdf_id: Optional[str], workspace_id: Optional[str], user_id: Optional[str]) -> bool:
    """Probe retriever for any document matching provided metadata triplet.

    This avoids false negatives on broad queries by checking existence via a blank query.
    """
    try:
        probe = retriever.get_relevant_documents(" ")
        _s = normalize_metadata_value
        for doc in probe:
            if (
                (pdf_id is None or doc.metadata.get('pdf_id') == _s(pdf_id)) and
                (workspace_id is None or doc.metadata.get('workspace_id') == _s(workspace_id)) and
                (user_id is None or doc.metadata.get('user_id') == _s(user_id))
            ):
                return True
        return False
    except Exception:
        return False
