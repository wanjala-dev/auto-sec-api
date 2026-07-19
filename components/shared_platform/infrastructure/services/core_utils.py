"""
Shared utility functions used across apps (responses, tokens, URLs, email helpers).
"""

from __future__ import annotations

import random
import secrets
import string
from io import BytesIO
import os
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site
from django.core.files import File
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from rest_framework.response import Response


def success_response(data, status_code: int = 200) -> Response:
    response = {"success": True, "data": data, "message": "Success"}
    return Response(response, status=status_code)


def error_response(message: str, status_code: int = 400) -> Response:
    response = {"success": False, "data": None, "message": message}
    return Response(response, status=status_code)


def generate_random_string(length: int = 6) -> str:
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for _ in range(length))


def generate_password(length: int = 8, charset: str = string.ascii_letters + string.digits) -> str:
    """Generate a random password."""
    return "".join(secrets.choice(charset) for _ in range(length))


def send_email(to_email: str, from_email: str, subject: str, text_content: str, html_template: str, context=None):
    if context is None:
        context = {}

    html_content = render_to_string(html_template, context)

    msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def get_comments(comment_queryset, parent_id=None):
    # get all comments with the current parent
    comments = comment_queryset.filter(parent_id=parent_id)
    result = []
    for comment in comments:
        # create a dictionary to represent the comment
        comment_dict = {
            "id": comment.id,
            "author": {
                "id": comment.author.id,
                "username": comment.author.username,
                "email": comment.author.email,
                "photo_url": comment.author.profile.photo_url,
            },
            "content": comment.content,
            "date_posted": comment.date_posted,
            "parent": parent_id,
            "has_children": False,
        }
        # recursively get the recipients of this comment
        recipients = get_comments(comment_queryset, parent_id=comment.id)
        if recipients:
            comment_dict["has_children"] = True
            comment_dict["recipients"] = recipients
        result.append(comment_dict)
    return result


def build_absolute_media_url(file_or_path, request=None, default_scheme=None) -> str:
    """
    Build an absolute URL for a media file using the Sites framework with
    graceful fallbacks to the incoming request and relative paths.
    """
    if not file_or_path:
        return ""

    try:
        candidate_url = file_or_path.url
    except AttributeError:
        candidate_url = str(file_or_path)

    if not candidate_url:
        return ""

    if candidate_url.startswith("http://") or candidate_url.startswith("https://"):
        return candidate_url

    if request is not None:
        try:
            return request.build_absolute_uri(candidate_url)
        except Exception:
            pass

    domain = ""
    try:
        current_site = get_current_site(request) if request is not None else Site.objects.get_current()
        domain = getattr(current_site, "domain", str(current_site)) or ""
    except Exception:
        domain = ""

    domain = domain.strip()
    if not domain:
        return candidate_url if candidate_url.startswith("/") else f"/{candidate_url}"

    scheme = None
    if request is not None:
        try:
            scheme = "https" if request.is_secure() else "http"
        except Exception:
            scheme = None
    if not scheme:
        scheme = default_scheme or "https"

    parsed = urlparse(domain if "://" in domain else f"//{domain}", scheme=scheme)
    scheme = parsed.scheme or scheme
    host = parsed.netloc or parsed.path
    host = host.strip().rstrip("/")
    if not host:
        return candidate_url if candidate_url.startswith("/") else f"/{candidate_url}"

    base = f"{scheme}://{host}"
    return urljoin(base + "/", candidate_url.lstrip("/"))


def build_image_variant(
    image_file,
    *,
    max_size: tuple[int, int] | None = None,
    quality: int = 85,
    format_name: str = "JPEG",
) -> File:
    """
    Build a resized, metadata-stripped image variant for storage.

    CONSTRAINTS:
    - Source must be a readable image file-like object.
    - Output is always re-encoded (default JPEG) and loses EXIF metadata.
    - max_size is a bounding box (no upscaling).

    DOES NOT HANDLE:
    - Animated images or multi-frame formats.
    - Format preservation beyond the requested format_name.
    - Color profile retention or advanced optimizations.
    """
    from PIL import Image, ImageOps

    try:
        pil_image = Image.open(image_file)
    except Exception as exc:
        raise ValueError("Unsupported or unreadable image file.") from exc

    pil_image = ImageOps.exif_transpose(pil_image)
    if max_size:
        pil_image.thumbnail(max_size)

    if pil_image.mode in ("RGBA", "P", "LA"):
        pil_image = pil_image.convert("RGB")

    data = list(pil_image.getdata())
    stripped = Image.new(pil_image.mode, pil_image.size)
    stripped.putdata(data)

    buffer = BytesIO()
    stripped.save(buffer, format_name, quality=quality, optimize=True)
    buffer.seek(0)

    original_name = getattr(image_file, "name", "") or "image"
    base_name, _ = os.path.splitext(original_name)
    extension = "jpg" if format_name.lower() in {"jpeg", "jpg"} else format_name.lower()
    filename = f"{base_name}.{extension}"
    return File(buffer, name=filename)


def normalize_frontend_base(candidate, default_scheme: str) -> str:
    """Normalize a candidate host/url into scheme://host form."""
    if not candidate:
        return ""
    candidate = str(candidate).strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"{default_scheme}://{candidate.lstrip('/')}"
    parsed = urlparse(candidate)
    host = parsed.netloc or parsed.path
    if not host:
        return ""
    scheme = parsed.scheme or default_scheme
    return f"{scheme}://{host.rstrip('/')}"


def resolve_frontend_base_url(*, site_domain: str = "", request=None) -> str:
    """Return the best frontend base URL for links.

    Settings-defined FRONTEND_URL / EMAIL_CLICK_REDIRECT_LINK win over the
    Django Site domain — in prod the Site domain is the API host
    (api.wanjala.art) and must NEVER be used for browser-facing links
    (CloudFront lives at a separate URL). The Site domain is a last-resort
    fallback for environments where API and frontend share a host.
    """
    default_scheme = "https"
    if request is not None:
        try:
            default_scheme = "https" if request.is_secure() else "http"
        except Exception:
            default_scheme = "https"

    domain = site_domain.strip() if isinstance(site_domain, str) else ""
    candidates = [
        # FRONTEND_URL is the single source of truth for user-facing links.
        # It must win even when the legacy vars below are explicitly set in
        # the environment (e.g. a stale EMAIL_CLICK_REDIRECT_LINK pointing at
        # the raw CloudFront URL).
        getattr(settings, "FRONTEND_URL", None),
        getattr(settings, "EMAIL_CLICK_REDIRECT_LINK", None),
        getattr(settings, "LOCALHOST_FRONTEND_URL", None),
        domain,
    ]

    for candidate in candidates:
        normalized = normalize_frontend_base(candidate, default_scheme)
        if normalized and normalized != f"{default_scheme}://example.com":
            return normalized

    return f"{default_scheme}://localhost:3000"
