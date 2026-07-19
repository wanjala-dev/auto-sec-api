"""Serializers for the social bounded context.

Extracted from ``components.identity.infrastructure.serializers.serializers``
to live within the owning bounded context.
"""

from rest_framework import serializers
from drf_writable_nested.serializers import WritableNestedModelSerializer

from infrastructure.persistence.social.models import Comment, Image, MessageModel, Post, Tag, ThreadModel
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace
from components.identity.mappers.rest.identity_serializers import UserSerializer


class ThreadSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    user = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id')
    receiver = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id')
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field='id', required=False)

    class Meta:
        model = ThreadModel
        depth = 4
        fields = (
            'id',
            'url',
            'user',
            'receiver',
            'workspace',
            'thread_type',
            'created_at',
            'is_archived',
            'is_starred',
            'archived_at',
            'starred_at',
        )


class MessageSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    sender_user = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id')
    receiver_user = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id')
    thread = serializers.SlugRelatedField(queryset=ThreadModel.objects.all(), slug_field='id', required=False)
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field='id', required=False)

    class Meta:
        model = MessageModel
        depth = 4
        fields = (
            'id',
            'url',
            'thread',
            'sender_user',
            'receiver_user',
            'body',
            'image',
            'date',
            'is_read',
            'workspace',
        )


class TagSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        ref_name = "tags_social"
        model = Tag
        depth = 4
        fields = (
            'id',
            'name',
        )


class PostSerializer(serializers.HyperlinkedModelSerializer):
    author = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id')
    likes = UserSerializer(many=True, read_only=True)
    dislikes = UserSerializer(many=True, read_only=True)
    shared_user = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id', required=False)
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        depth = 4
        fields = (
            'id',
            'url',
            'shared_body',
            'body',
            'created_on',
            'shared_on',
            'author',
            'shared_user',
            'likes',
            'dislikes',
            'tags',
        )


class CommentSerializer(serializers.HyperlinkedModelSerializer):
    author = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field='id')
    likes = UserSerializer(many=True, read_only=True)
    dislikes = UserSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    post = serializers.SlugRelatedField(queryset=Post.objects.all(), slug_field='id')
    parent = serializers.SlugRelatedField(queryset=Comment.objects.all(), slug_field='id', required=False)

    class Meta:
        model = Comment
        depth = 4
        fields = (
            'id',
            'url',
            'comment',
            'created_on',
            'author',
            'post',
            'likes',
            'dislikes',
            'parent',
            'tags',
        )
