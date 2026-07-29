"""Serializers for the brand asset library endpoints (input validation)."""

from __future__ import annotations

from rest_framework import serializers


class BrandAssetCreateSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=500)
    storage_key = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    label = serializers.CharField(required=False, allow_blank=True, max_length=120, default="")
    alt_text = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    kind = serializers.ChoiceField(choices=["photo", "logo", "graphic"], required=False, default="photo")


class BrandAssetUpdateSerializer(serializers.Serializer):
    label = serializers.CharField(required=False, allow_blank=True, max_length=120)
    alt_text = serializers.CharField(required=False, allow_blank=True, max_length=255)
