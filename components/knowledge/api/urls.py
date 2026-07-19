"""
Knowledge API URLs - RAG and LLM provider management

ViewSet + Router based URL configuration:
- EmbeddingViewSet: embeddings endpoints
- LLMViewSet: llms endpoints
- VectorStoreViewSet: vector_stores endpoints
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from components.knowledge.api import controller

# Initialize router and register ViewSets
router = DefaultRouter()
router.register(r'embeddings', controller.EmbeddingViewSet, basename='embedding')
router.register(r'llms', controller.LLMViewSet, basename='llm')
router.register(r'vector_stores', controller.VectorStoreViewSet, basename='vector-store')

urlpatterns = [
    path('', include(router.urls)),
]
