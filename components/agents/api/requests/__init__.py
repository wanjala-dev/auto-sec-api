"""Request DTOs for AI API endpoints."""
from __future__ import annotations

from .create_agent_request import CreateAgentRequest
from .execute_agent_request import ExecuteAgentRequest
from .patch_agent_profile_request import PatchAgentProfileRequest
from .patch_agent_settings_request import PatchAgentSettingsRequest
from .rate_agent_request import RateAgentRequest
from .comment_agent_request import CommentAgentRequest
from .share_agent_request import ShareAgentRequest
from .update_teammate_profile_request import UpdateTeammateProfileRequest
from .set_agent_entitlement_request import SetAgentEntitlementRequest
from .add_agent_system_message_request import AddAgentSystemMessageRequest
from .deep_run_plan_request import DeepRunPlanRequest
from .deep_plan_and_run_request import DeepPlanAndRunRequest
from .create_conversation_request import CreateConversationRequest
from .add_conversation_message_request import AddConversationMessageRequest
from .pdf_create_message_request import PdfCreateMessageRequest
from .pdf_create_conversation_request import PdfCreateConversationRequest
from .search_pdf_content_request import SearchPdfContentRequest
from .create_embedding_request import CreateEmbeddingRequest
from .create_embeddings_batch_request import CreateEmbeddingsBatchRequest
from .similarity_search_request import SimilaritySearchRequest
from .conversation_chain_request import ConversationChainRequest
from .qa_chain_request import QAChainRequest
from .retrieval_chain_request import RetrievalChainRequest
from .openai_chat_request import OpenaiChatRequest
from .langchain_chat_request import LangchainChatRequest
from .chat_with_workspace_request import ChatWithWorkspaceRequest
from .search_workspace_content_request import SearchWorkspaceContentRequest
from .chat_with_images_request import ChatWithImagesRequest
from .summarize_pdf_request import SummarizePdfRequest
from .create_document_request import CreateDocumentRequest
from .search_documents_request import SearchDocumentsRequest

__all__ = [
    "CreateAgentRequest",
    "ExecuteAgentRequest",
    "PatchAgentProfileRequest",
    "PatchAgentSettingsRequest",
    "RateAgentRequest",
    "CommentAgentRequest",
    "ShareAgentRequest",
    "UpdateTeammateProfileRequest",
    "SetAgentEntitlementRequest",
    "AddAgentSystemMessageRequest",
    "DeepRunPlanRequest",
    "DeepPlanAndRunRequest",
    "CreateConversationRequest",
    "AddConversationMessageRequest",
    "PdfCreateMessageRequest",
    "PdfCreateConversationRequest",
    "SearchPdfContentRequest",
    "CreateEmbeddingRequest",
    "CreateEmbeddingsBatchRequest",
    "SimilaritySearchRequest",
    "ConversationChainRequest",
    "QAChainRequest",
    "RetrievalChainRequest",
    "OpenaiChatRequest",
    "LangchainChatRequest",
    "ChatWithWorkspaceRequest",
    "SearchWorkspaceContentRequest",
    "ChatWithImagesRequest",
    "SummarizePdfRequest",
    "CreateDocumentRequest",
    "SearchDocumentsRequest",
]
