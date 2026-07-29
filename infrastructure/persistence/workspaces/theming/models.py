import uuid

from django.conf import settings
from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class WorkspaceTheme(models.Model):
    """Per-workspace brand kit: seed(s), logo slots, fonts, and voice.

    Only the seed is stored — the full accessible ~18-token palette is DERIVED
    from it by ``BrandResolutionService`` (never persisted as 40 colours). Blank
    seeds mean "use the Auto-Sec default". Fonts follow the same contract: the
    row stores a ``BrandFontOption`` catalog *key*, never a stack. Voice is the
    workspace's canonical editorial voice (brand kit is the single home).

    Design: docs/plans/WORKSPACE_THEMING_DESIGN_2026-07-09.md (source repo)
    """

    class Mode(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"
        AUTO = "auto", "Auto"

    class VoiceTone(models.TextChoices):
        # Mirrors the presets the workspace AI config historically offered, so
        # the brand-kit canonical move is a straight data copy.
        FORMAL = "formal", "Formal"
        WARM = "warm", "Warm"
        ACTIVIST = "activist", "Activist"
        TECHNICAL = "technical", "Technical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.CASCADE,
        related_name="theme",
    )
    brand_seed = models.CharField(max_length=9, blank=True, default="")
    secondary_seed = models.CharField(max_length=9, blank=True, default="")
    logo_url = models.CharField(max_length=500, blank=True, default="")
    # Fixed logo slots (seed-not-scale: singleton brand inputs, not a library).
    logo_icon_url = models.CharField(max_length=500, blank=True, default="")
    logo_dark_url = models.CharField(max_length=500, blank=True, default="")
    favicon_url = models.CharField(max_length=500, blank=True, default="")
    # Font catalog keys; "" = Auto-Sec default typography.
    font_heading = models.CharField(max_length=48, blank=True, default="")
    font_body = models.CharField(max_length=48, blank=True, default="")
    # Canonical workspace voice. Never exposed on public endpoints.
    voice_tone = models.CharField(max_length=24, blank=True, default="", choices=VoiceTone.choices)
    voice_guidelines = models.TextField(blank=True, default="")
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.LIGHT)
    radius = models.CharField(max_length=16, blank=True, default="")
    login_branding_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace_theme"

    def __str__(self) -> str:
        return f"WorkspaceTheme<{self.workspace_id}>"


class BrandAsset(models.Model):
    """A workspace's brand image library (photos, extra logos, graphics).

    The library complements the fixed logo SLOTS on ``WorkspaceTheme`` —
    slots are singleton brand inputs; assets are the reusable many (hero
    shots, team photos) that public pages pull from. Bytes live in object
    storage (uploaded via the shared presigned-PUT flow); the row stores the
    URL + metadata. ``deleted`` is the recycle-bin soft-delete flag (adapter
    registered as ``entity_type="brand_asset"``).
    """

    class Kind(models.TextChoices):
        PHOTO = "photo", "Photo"
        LOGO = "logo", "Logo"
        GRAPHIC = "graphic", "Graphic"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="brand_assets",
    )
    url = models.CharField(max_length=500)
    # Object-store key, kept for purge-time cleanup (best-effort).
    storage_key = models.CharField(max_length=500, blank=True, default="")
    label = models.CharField(max_length=120, blank=True, default="")
    alt_text = models.CharField(max_length=255, blank=True, default="")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.PHOTO)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brand_asset"
        indexes = [
            models.Index(fields=["workspace", "deleted", "-created_at"]),
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"BrandAsset<{self.id}>"


class BrandFontOption(models.Model):
    """Curated platform font catalog (seeded by ``seed_brand_fonts``).

    Not workspace-scoped — a fixed menu the brand settings UI fetches (the
    frontend never hardcodes font choices). ``css_stack`` is the full fallback
    stack (the email/PDF guarantee); ``google_family`` is the Google Fonts css2
    family spec for surfaces that can load webfonts ("" = pure system stack).
    """

    class Category(models.TextChoices):
        HEADING = "heading", "Heading"
        BODY = "body", "Body"
        BOTH = "both", "Both"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=48, unique=True)
    label = models.CharField(max_length=64)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.BOTH)
    css_stack = models.CharField(max_length=255)
    google_family = models.CharField(max_length=128, blank=True, default="")
    sort_order = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brand_font_option"
        ordering = ("sort_order", "label")

    def __str__(self) -> str:
        return f"BrandFontOption<{self.key}>"
