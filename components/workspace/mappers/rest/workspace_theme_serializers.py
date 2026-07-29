"""Serializers for the admin workspace-theme endpoint (input validation)."""

from __future__ import annotations

from rest_framework import serializers

VOICE_TONE_CHOICES = ["", "formal", "warm", "activist", "technical"]


class WorkspaceThemeUpdateSerializer(serializers.Serializer):
    brand_seed = serializers.CharField(required=False, allow_blank=True, max_length=9, default="")
    secondary_seed = serializers.CharField(required=False, allow_blank=True, max_length=9, default="")
    logo_url = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    mode = serializers.ChoiceField(choices=["light", "dark", "auto"], required=False, default="light")
    logo_icon_url = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    logo_dark_url = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    favicon_url = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    # Catalog keys — existence is validated in the use case against the catalog.
    font_heading = serializers.CharField(required=False, allow_blank=True, max_length=48, default="")
    font_body = serializers.CharField(required=False, allow_blank=True, max_length=48, default="")
    voice_tone = serializers.ChoiceField(choices=VOICE_TONE_CHOICES, required=False, allow_blank=True, default="")
    # Free text that flows into AI drafting goals — hard cap keeps the prompt
    # bounded (see the brand-voice injection framing in the content adapter).
    voice_guidelines = serializers.CharField(
        required=False, allow_blank=True, max_length=1000, default="", trim_whitespace=True
    )
