"""
Sync the Django Site record from environment variables.

Usage:
  python manage.py configure_site

Reads from environment:
  SITE_DOMAIN       — The API domain (e.g. api.wanjala.art). Falls back to ALLOWED_HOSTS[0].
  SITE_NAME         — Display name (e.g. "Wanjala API"). Defaults to the domain.
  FRONTEND_URL      — The frontend base URL (e.g. https://demo.octopusintl.org).
                      Written to the Site's metadata and used by LOCALHOST_FRONTEND_URL.

Idempotent — safe to run on every deploy. Updates the existing Site record
matched by SITE_ID (from settings) or creates one if missing.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync Django Site domain and frontend URL from environment variables."

    def handle(self, *args, **options):
        from django.contrib.sites.models import Site

        site_id = getattr(settings, "SITE_ID", 1)

        # Resolve domain
        domain = os.environ.get("SITE_DOMAIN", "").strip()
        if not domain:
            allowed = getattr(settings, "ALLOWED_HOSTS", [])
            # Pick the first non-wildcard host
            domain = next((h for h in allowed if h and h != "*"), "")
        if not domain:
            self.stderr.write(self.style.WARNING(
                "No SITE_DOMAIN or ALLOWED_HOSTS configured — skipping."
            ))
            return

        name = os.environ.get("SITE_NAME", "").strip() or domain

        site, created = Site.objects.update_or_create(
            id=site_id,
            defaults={"domain": domain, "name": name},
        )

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} Site #{site.id}: domain={site.domain}, name={site.name}"
        ))

        # Log the frontend URL for visibility
        frontend_url = os.environ.get(
            "FRONTEND_URL",
            getattr(settings, "LOCALHOST_FRONTEND_URL", ""),
        )
        if frontend_url:
            self.stdout.write(f"Frontend URL: {frontend_url}")
