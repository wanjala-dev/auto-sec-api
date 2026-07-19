"""Views for news articles, categories, tags, and comments."""

from __future__ import annotations

from django.http import Http404
from rest_framework import generics, permissions, status
from rest_framework.generics import (
    CreateAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.response import Response

from components.content.application.service import ContentService
from components.content.api.permissions import IsOwnerOrReadOnly
from components.content.mappers.rest.content_serializers import (
    CategorySerializer,
    CommentCreateSerializer,
    CommentSerializer,
    NewsGetSerializer,
    NewsSerializer,
    TagSerializer,
)
from components.shared_platform.application.providers.core_utils_provider import (
    get_core_utils_provider,
)


# Module-level service instance
_content_service = ContentService()


class NewsAPIView(ListCreateAPIView):
    """News (blog) collection endpoint mounted at ``/content/``.

    ``GET`` lists news articles (read serializer), with an optional
    ``?slug=`` filter (fetch-by-slug) and ``?workspace=`` filter.
    ``POST`` creates a news article (write serializer). Single-article
    retrieve / update / delete live on :class:`NewsDetailView` at
    ``/content/articles/<news_id>/``.
    """

    serializer_class = NewsSerializer
    name = 'news'
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)

    def get_serializer_class(self):
        # Reads use the richer read serializer (author, category, tags,
        # media); writes use the writable NewsSerializer so the create
        # response shape is byte-identical to the previous behaviour.
        if self.request.method == 'GET':
            return NewsGetSerializer
        return NewsSerializer

    def get_queryset(self):
        queryset = _content_service.get_news_queryset()
        slug = self.request.query_params.get('slug')
        if slug:
            queryset = _content_service.filter_news_by_slug(queryset, slug)
        workspace_id = self.request.query_params.get('workspace')
        if workspace_id:
            queryset = _content_service.filter_news_by_workspace(queryset, workspace_id)
        return queryset

    def post(self, request, *args, **kwargs):
        # ``get_serializer`` resolves to NewsSerializer (write) for POST
        # and injects the request into context (needed by the nested
        # author serializer's hyperlinked field).
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(author=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NewsDetailView(RetrieveUpdateDestroyAPIView):
    """Single news-article resource at ``/content/articles/<news_id>/``.

    ``GET`` retrieves (read serializer), ``PATCH``/``PUT`` update, and
    ``DELETE`` removes a single article resolved by its UUID.
    """

    name = 'news-detail'
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)
    lookup_field = 'id'
    lookup_url_kwarg = 'news_id'

    def get_queryset(self):
        return _content_service.get_news_queryset()

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return NewsGetSerializer
        return NewsSerializer

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        # ``get_serializer`` resolves to NewsSerializer (write) and injects
        # request context for the nested author serializer.
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContentTagList(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)
    serializer_class = TagSerializer
    name = 'news-tag-list'

    def get_queryset(self):
        return _content_service.list_tags()


class ContentCategoryList(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)
    serializer_class = CategorySerializer
    name = 'news-category-list'

    def get_queryset(self):
        return _content_service.list_categories()


class NewsGetView(ListAPIView):
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)
    serializer_class = NewsGetSerializer
    name = 'get-news'

    def get_queryset(self):
        queryset = _content_service.get_news_with_comments()
        workspace_id = self.kwargs.get('workspace_id')
        if workspace_id:
            queryset = _content_service.filter_news_by_workspace(queryset, workspace_id)
        return queryset

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        for news_item in response.data['results']:
            try:
                news_item_id = news_item['id']
            except KeyError:
                continue
            news_item_comments = _content_service.get_comments_for_news(news_item_id)
            comments = get_core_utils_provider().get_comments(news_item_comments)
            news_item['workspace_comments'] = comments
        return response


class CommentCreateView(CreateAPIView):
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)
    serializer_class = CommentCreateSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid():
            news_title = serializer.validated_data.get('news')
            try:
                news = _content_service.get_news_by_title(news_title)
            except Exception:
                raise Http404
            comment = serializer.save(author=request.user, news=news)
            comment_serializer = CommentSerializer(comment, context={'request': request})
            return Response(comment_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContentCommentReplyView(CreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CommentSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        comment_id = self.kwargs.get('comment_id')
        try:
            parent_comment = _content_service.get_comment_by_id(comment_id)
        except Exception:
            raise Http404
        news_id = parent_comment.news.id
        serializer.save(author=self.request.user, news_id=news_id, parent=parent_comment)
