"""Serializers for news articles, categories, tags, and comments."""

from __future__ import annotations

from rest_framework import serializers

from infrastructure.persistence.workspaces.news.models import News, Category, Tag, Comment
from components.shared_platform.mappers.rest.uploads_serializers import FileSerializer
from components.identity.mappers.rest.identity_serializers import UserSerializer
from drf_writable_nested.serializers import WritableNestedModelSerializer


class CategorySerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    news_count = serializers.IntegerField()

    class Meta:
        model = Category
        fields = '__all__'


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ('id', 'name')


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    news = serializers.SlugRelatedField(queryset=News.objects.all(), slug_field='id', allow_null=True)

    class Meta:
        model = Comment
        fields = ['id', 'author', 'parent', 'content', 'date_posted', 'news']


class CommentCreateSerializer(serializers.ModelSerializer):
    news = serializers.CharField(max_length=255, allow_null=True)

    class Meta:
        model = Comment
        fields = ['id', 'content', 'news']
        read_only_fields = ['id']


class NewsGetSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    category = serializers.StringRelatedField()
    tags = serializers.StringRelatedField(many=True)
    workspace_comments = CommentSerializer(many=True, read_only=True)
    media = FileSerializer(many=True, read_only=True)

    class Meta:
        model = News
        fields = ['id', 'workspace', 'image', 'title', 'excerpt', 'body', 'media', 'pub_date', 'author', 'featured',
                  'slug', 'status', 'category', 'tags', 'workspace_comments', 'created_at']


class NewsSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(queryset=Category.objects.all(), slug_field='name', allow_null=True)

    class Meta:
        model = News
        fields = '__all__'
        # ``author`` is set by the controller from ``request.user`` (never
        # supplied by the client). Marking it read-only keeps it out of
        # input validation while preserving the create response shape
        # (the author UUID is still serialized on output, unchanged).
        extra_kwargs = {'author': {'read_only': True}}
