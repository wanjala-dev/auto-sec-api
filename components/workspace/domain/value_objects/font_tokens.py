"""Value object: the resolved font token pair (heading + body).

Fonts follow the same seed-not-scale contract as colours: the workspace stores
a catalog *key* (``WorkspaceTheme.font_heading`` / ``font_body``), and the
resolver emits the full token — family name, complete CSS fallback stack, and
the Google Fonts family spec for surfaces that can load webfonts. Email/PDF
renderers use ``stack`` only (email clients largely ignore webfonts — the
fallback stack IS the email guarantee); public web pages additionally load
``google_family`` when non-empty.

The defaults here are the resolver fallback for an unset/unknown key and for
deploys where the font catalog has not been seeded yet — behaviour is safe
before ``seed_brand_fonts`` runs. Framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FontToken:
    """One resolved font choice (heading or body)."""

    family: str  # display name, e.g. "Poppins"
    stack: str  # full CSS font-family stack incl. fallbacks
    google_family: str  # Google Fonts css2 family spec, "" = system/email-safe

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "stack": self.stack,
            "google_family": self.google_family,
        }


@dataclass(frozen=True)
class FontTokenSet:
    """The resolved heading + body pair emitted on every brand payload."""

    heading: FontToken
    body: FontToken

    def as_dict(self) -> dict:
        return {"heading": self.heading.as_dict(), "body": self.body.as_dict()}


# The default platform typography (matches the frontend's default type scale).
DEFAULT_HEADING = FontToken(
    family="Poppins",
    stack="'Poppins', 'Helvetica Neue', Arial, sans-serif",
    google_family="Poppins:wght@500;600;700",
)
DEFAULT_BODY = FontToken(
    family="Inter",
    stack="'Inter', 'Helvetica Neue', Arial, sans-serif",
    google_family="Inter:wght@400;500;600",
)
DEFAULT_FONTS = FontTokenSet(heading=DEFAULT_HEADING, body=DEFAULT_BODY)
