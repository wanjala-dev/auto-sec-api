"""
Knowledge API Controller - RAG and LLM provider management

Converted to ViewSet + Router class-based views:
- EmbeddingViewSet: create, batch, similarity, providers
- LLMViewSet: openai_chat, langchain_chat, available_models, providers
- VectorStoreViewSet: documents, search, providers
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from components.shared_kernel.application.providers.django_orm_provider import (
    get_django_orm_provider as _get_django_orm_provider,
)
_django_orm = _get_django_orm_provider()
Count = _django_orm.Count
Prefetch = _django_orm.Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from components.knowledge.application.service import KnowledgeService
from components.agents.application.providers.ai_models_provider import get_ai_models_provider

logger = logging.getLogger(__name__)

_ai_models = get_ai_models_provider()
Document = _ai_models.Document
DocumentChunk = _ai_models.DocumentChunk

knowledge_service = KnowledgeService()


def _schema(request_body: bool = False):
    """Helper to create schema decorators"""
    if request_body:
        return extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    return extend_schema(responses=OpenApiTypes.OBJECT)


# ── EMBEDDINGS VIEWSET ──

class EmbeddingViewSet(viewsets.ViewSet):
    """
    ViewSet for embedding operations:
    - create: Create embedding for single text
    - batch: Create embeddings for multiple texts
    - similarity: Find similar texts based on embedding similarity
    - providers: Get available embedding providers
    """

    @_schema(request_body=True)
    def create(self, request):
        """
        Create embeddings for text
        POST /embeddings/create/
        """
        try:
            text = request.data.get('text', '')
            if not text:
                return Response(
                    {'error': 'Text is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check for mock mode
            use_mock = request.data.get('mock', False)
            if use_mock:
                return Response({
                    'text': text,
                    'embedding': [0.1] * 1536,  # Mock embedding vector
                    'dimension': 1536,
                    'model': 'text-embedding-ada-002',
                    'mock': True
                })

            provider = request.data.get('provider', 'openai')
            model_name = request.data.get('model_name')

            # Initialize embeddings using service
            try:
                embeddings_kwargs = {}
                if model_name:
                    embeddings_kwargs['model_name'] = model_name

                embeddings = knowledge_service.get_embeddings_port(
                    provider=provider,
                    **embeddings_kwargs
                )
            except Exception as e:
                return Response(
                    {'error': f'Embeddings configuration error: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Create embedding
            embedding = embeddings.embed_query(text)

            return Response({
                'text': text,
                'embedding': embedding,
                'dimension': len(embedding),
                'model': 'text-embedding-ada-002'
            })

        except Exception as e:
            return Response(
                {'error': f'Embedding error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    @action(detail=False, methods=['post'])
    def batch(self, request):
        """
        Create embeddings for multiple texts
        POST /embeddings/batch/
        """
        try:
            texts = request.data.get('texts', [])
            if not texts or not isinstance(texts, list):
                return Response(
                    {'error': 'Texts array is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check for mock mode
            use_mock = request.data.get('mock', False)
            if use_mock:
                return Response({
                    'texts': texts,
                    'embeddings': [[0.1] * 1536 for _ in texts],
                    'count': len(texts),
                    'dimension': 1536,
                    'model': 'text-embedding-ada-002',
                    'mock': True
                })

            provider = request.data.get('provider', 'openai')
            model_name = request.data.get('model_name')

            # Initialize embeddings using factory
            try:
                embeddings_kwargs = {}
                if model_name:
                    embeddings_kwargs['model_name'] = model_name

                embeddings = knowledge_service.get_embeddings_port(
                    provider=provider,
                    **embeddings_kwargs
                )
            except Exception as e:
                return Response(
                    {'error': f'Embeddings configuration error: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Create embeddings
            embedding_list = embeddings.embed_documents(texts)

            return Response({
                'texts': texts,
                'embeddings': embedding_list,
                'count': len(texts),
                'dimension': len(embedding_list[0]) if embedding_list else 0,
                'model': 'text-embedding-ada-002'
            })

        except Exception as e:
            return Response(
                {'error': f'Batch embedding error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    @action(detail=False, methods=['post'])
    def similarity(self, request):
        """
        Find similar texts based on embedding similarity
        POST /embeddings/similarity/
        """
        try:
            query_text = request.data.get('query', '')
            texts = request.data.get('texts', [])

            if not query_text or not texts:
                return Response(
                    {'error': 'Query and texts are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check for mock mode
            use_mock = request.data.get('mock', False)
            if use_mock:
                return Response({
                    'query': query_text,
                    'results': [
                        {'text': text, 'similarity': 0.8 - (i * 0.1)}
                        for i, text in enumerate(texts[:3])
                    ],
                    'mock': True
                })

            provider = request.data.get('provider', 'openai')
            model_name = request.data.get('model_name')

            # Initialize embeddings using factory
            try:
                embeddings_kwargs = {}
                if model_name:
                    embeddings_kwargs['model_name'] = model_name

                embeddings = knowledge_service.get_embeddings_port(
                    provider=provider,
                    **embeddings_kwargs
                )
            except Exception as e:
                return Response(
                    {'error': f'Embeddings configuration error: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Create embeddings
            query_embedding = embeddings.embed_query(query_text)
            text_embeddings = embeddings.embed_documents(texts)

            # Calculate similarities (simple cosine similarity)
            similarities = []
            for i, text_embedding in enumerate(text_embeddings):
                similarity = np.dot(query_embedding, text_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(text_embedding)
                )
                similarities.append({
                    'text': texts[i],
                    'similarity': float(similarity)
                })

            # Sort by similarity
            similarities.sort(key=lambda x: x['similarity'], reverse=True)

            return Response({
                'query': query_text,
                'results': similarities[:5]  # Top 5 results
            })

        except Exception as e:
            return Response(
                {'error': f'Similarity search error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema()
    @action(detail=False, methods=['get'])
    def providers(self, request):
        """
        Get available embedding providers and their information
        GET /embeddings/providers/
        """
        try:
            providers = knowledge_service.list_embeddings_providers()

            provider_info = {}
            for provider in providers:
                provider_info[provider] = knowledge_service.get_embeddings_provider_info(provider)

            return Response({
                'providers': provider_info,
                'default': 'openai'
            })

        except Exception as e:
            return Response(
                {'error': f'Failed to get providers: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ── LLM VIEWSET ──

class LLMViewSet(viewsets.ViewSet):
    """
    ViewSet for LLM operations:
    - openai_chat: Direct OpenAI chat completion
    - langchain_chat: LangChain-based chat
    - available_models: Get list of available models
    - providers: Get available LLM providers
    """

    @_schema(request_body=True)
    @action(detail=False, methods=['post'])
    def openai_chat(self, request):
        """
        Direct OpenAI chat completion using OpenAI API
        POST /llms/openai_chat/
        """
        try:
            message = request.data.get('message', '')
            if not message:
                return Response(
                    {'error': 'Message is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            use_mock = request.data.get('mock', False)
            if use_mock:
                return Response({
                    'message': message,
                    'response': f"Mock OpenAI response: I received '{message}'",
                    'model': 'gpt-3.5-turbo',
                    'provider': 'openai',
                    'mock': True
                })

            try:
                llm = knowledge_service.get_llm_port(
                    provider='openai',
                    model_name="gpt-3.5-turbo",
                    temperature=0.7
                )
            except Exception as e:
                return Response(
                    {'error': f'OpenAI configuration error: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Chat via the port — no LangChain imports needed here
            result = llm.chat([
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": message},
            ])

            return Response({
                'message': message,
                'response': result.content,
                'model': 'gpt-3.5-turbo',
                'provider': 'openai'
            })

        except Exception as e:
            return Response(
                {'error': f'OpenAI error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema(request_body=True)
    @action(detail=False, methods=['post'])
    def langchain_chat(self, request):
        """
        LangChain-based chat using ChatOpenAI
        POST /llms/langchain_chat/
        """
        try:
            message = request.data.get('message', '')
            if not message:
                return Response(
                    {'error': 'Message is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            use_mock = request.data.get('mock', False)
            if use_mock:
                return Response({
                    'message': message,
                    'response': f"Mock LangChain response: I received '{message}'",
                    'model': 'gpt-3.5-turbo',
                    'provider': 'langchain',
                    'mock': True
                })

            try:
                llm = knowledge_service.get_llm_port(
                    provider='openai',
                    model_name="gpt-3.5-turbo",
                    temperature=0.7,
                    max_tokens=500
                )
            except Exception as e:
                return Response(
                    {'error': f'LLM configuration error: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            result = llm.chat([
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": message},
            ])

            return Response({
                'message': message,
                'response': result.content,
                'model': 'gpt-3.5-turbo',
                'provider': 'openai'
            })

        except Exception as e:
            return Response(
                {'error': f'LLM error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @_schema()
    @action(detail=False, methods=['get'])
    def available_models(self, request):
        """
        Get list of available LLM models
        GET /llms/available_models/
        """
        return Response({
            'models': [
                {
                    'name': 'gpt-3.5-turbo',
                    'provider': 'openai',
                    'type': 'chat',
                    'max_tokens': 4096
                },
                {
                    'name': 'gpt-4',
                    'provider': 'openai',
                    'type': 'chat',
                    'max_tokens': 8192
                }
            ]
        })

    @_schema()
    @action(detail=False, methods=['get'])
    def providers(self, request):
        """
        Get available LLM providers and their information
        GET /llms/providers/
        """
        try:
            providers = knowledge_service.list_llm_providers()

            provider_info = {}
            for provider in providers:
                provider_info[provider] = knowledge_service.get_llm_provider_info(provider)

            return Response({
                'providers': provider_info,
                'default': 'openai'
            })

        except Exception as e:
            return Response(
                {'error': f'Failed to get providers: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ── VECTOR STORE VIEWSET ──

class VectorStoreViewSet(viewsets.ViewSet):
    """
    ViewSet for vector store operations:
    - create: Create a new document for vector storage
    - list: List all documents
    - retrieve: Get document details
    - search: Search documents using vector similarity
    - providers: Get available vector store providers
    """

    @extend_schema(
        operation_id="knowledge_vector_stores_documents_create",
        request=OpenApiTypes.OBJECT,
        responses=OpenApiTypes.OBJECT,
    )
    def create(self, request):
        """
        Create a new document for vector storage
        POST /vector_stores/

        ``workspace_id`` is required — knowledge documents are
        tenant-scoped at the DB layer and a missing workspace would
        create an orphan row that any other workspace could in
        principle read.  See Tier 2 #4 in
        ``docs/plans/RAG_AUDIT_AND_ROADMAP.md``.
        """
        try:
            title = request.data.get('title', '')
            content = request.data.get('content', '')
            source = request.data.get('source', '')
            metadata = request.data.get('metadata', {})
            workspace_id = request.data.get('workspace_id') or (metadata or {}).get('workspace_id')

            # Support both 'content' and 'text' fields
            if not content:
                content = request.data.get('text', '')

            if not title or not content:
                return Response(
                    {'error': 'Title and content (or text) are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not workspace_id:
                return Response(
                    {
                        'error': (
                            'workspace_id is required — knowledge '
                            'documents must be tenant-scoped.  Pass it '
                            'either at the top level of the request '
                            'body or inside metadata.workspace_id.'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            document = knowledge_service.create_document(
                title=title,
                content=content,
                source=source,
                metadata=metadata,
                workspace_id=str(workspace_id),
            )

            # Check if we should store in vector store
            store_in_vector_store = request.data.get('store', False)
            provider = request.data.get('provider', 'elasticsearch')

            if store_in_vector_store:
                try:
                    # Create vector store and store the document
                    vector_store = knowledge_service.get_vector_store_port(provider=provider)
                    # Note: This interface depends on vector store adapter's add method
                    if hasattr(vector_store, 'add_texts'):
                        vector_store.add_texts(
                            texts=[content],
                            metadatas=[{**metadata, 'title': title, 'source': source, 'document_id': str(document.id)}]
                        )

                    return Response({
                        'document_id': str(document.id),
                        'title': document.title,
                        'source': document.source,
                        'created_at': document.created_at,
                        'metadata': document.metadata,
                        'stored_in_vector_store': True,
                        'provider': provider
                    })
                except Exception as e:
                    # If vector store storage fails, still return the document
                    return Response({
                        'document_id': str(document.id),
                        'title': document.title,
                        'source': document.source,
                        'created_at': document.created_at,
                        'metadata': document.metadata,
                        'stored_in_vector_store': False,
                        'vector_store_error': str(e)
                    })

            return Response({
                'document_id': str(document.id),
                'title': document.title,
                'source': document.source,
                'created_at': document.created_at,
                'metadata': document.metadata
            })

        except Exception as e:
            return Response(
                {'error': f'Failed to create document: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        operation_id="knowledge_vector_stores_documents_list",
        request=None,
        responses=OpenApiTypes.OBJECT,
    )
    def list(self, request):
        """
        List all documents
        GET /vector_stores/
        """
        try:
            try:
                page = int(request.query_params.get('page', 1))
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = int(request.query_params.get('page_size', 25))
            except (TypeError, ValueError):
                page_size = 25
            page_size = max(1, min(page_size, 100))

            documents_qs = (
                Document.objects
                .annotate(chunk_count=Count('chunks'))
                .order_by('-created_at')
            )

            paginator = Paginator(documents_qs, page_size)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)

            documents = [
                {
                    'document_id': str(doc.id),
                    'title': doc.title,
                    'source': doc.source,
                    'created_at': doc.created_at,
                    'updated_at': doc.updated_at,
                    'chunk_count': getattr(doc, 'chunk_count', 0),
                }
                for doc in page_obj
            ]

            return Response({
                'count': paginator.count,
                'page': page_obj.number,
                'page_size': page_size,
                'num_pages': paginator.num_pages,
                'documents': documents,
            })

        except Exception as e:
            return Response(
                {'error': f'Failed to list documents: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        operation_id="knowledge_vector_stores_documents_detail",
        request=None,
        responses=OpenApiTypes.OBJECT,
    )
    def retrieve(self, request, pk=None):
        """
        Get document details
        GET /vector_stores/{document_id}/
        """
        try:
            document = Document.objects.prefetch_related(
                Prefetch('chunks', queryset=DocumentChunk.objects.order_by('chunk_index'))
            ).get(id=pk)
            chunks = document.chunks.all()

            return Response({
                'document_id': str(document.id),
                'title': document.title,
                'content': document.content,
                'source': document.source,
                'created_at': document.created_at,
                'updated_at': document.updated_at,
                'metadata': document.metadata,
                'chunks': [
                    {
                        'chunk_id': str(chunk.id),
                        'content': chunk.content,
                        'chunk_index': chunk.chunk_index,
                        'metadata': chunk.metadata
                    }
                    for chunk in chunks
                ]
            })

        except Document.DoesNotExist:
            return Response(
                {'error': 'Document not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to get document: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        operation_id="knowledge_vector_stores_documents_search",
        request=OpenApiTypes.OBJECT,
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=['post'])
    def search(self, request):
        """
        Search documents using vector similarity
        POST /vector_stores/search/
        """
        try:
            query = request.data.get('query', '')
            provider = request.data.get('provider', 'elasticsearch')
            try:
                k = int(request.data.get('k', 4))
            except (TypeError, ValueError):
                k = 4
            k = max(1, min(k, 20))

            if not query:
                return Response(
                    {'error': 'Query is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check for mock mode
            use_mock = request.data.get('mock', False)
            if use_mock:
                return Response({
                    'query': query,
                    'results': [
                        {
                            'content': f"Mock document {i}",
                            'score': 0.9 - (i * 0.1),
                            'metadata': {'source': f'mock_doc_{i}'}
                        }
                        for i in range(min(k, 3))
                    ],
                    'provider': provider,
                    'mock': True
                })

            # Create retriever
            search_results = knowledge_service.get_vector_store_port(
                provider=provider,
            ).search(
                query=query,
                k=k
            )

            # Convert search results to response format
            results_data = []
            if isinstance(search_results, list):
                for doc in search_results:
                    if hasattr(doc, 'content'):
                        results_data.append({
                            'content': doc.content,
                            'metadata': doc.metadata,
                            'score': getattr(doc, 'score', 0.0)
                        })
                    else:
                        results_data.append({
                            'content': str(doc),
                            'metadata': {},
                            'score': 0.0
                        })

            return Response({
                'query': query,
                'results': results_data,
                'provider': provider
            })

        except Exception as e:
            return Response(
                {'error': f'Search failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        operation_id="knowledge_vector_stores_providers_list",
        request=None,
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=['get'])
    def providers(self, request):
        """
        Get available vector store providers
        GET /vector_stores/providers/
        """
        try:
            providers = knowledge_service.list_vector_store_providers()

            provider_info = {}
            for provider in providers:
                provider_info[provider] = knowledge_service.get_vector_store_provider_info(provider)

            return Response({
                'providers': provider_info,
                'default': 'elasticsearch'
            })

        except Exception as e:
            return Response(
                {'error': f'Failed to get providers: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
