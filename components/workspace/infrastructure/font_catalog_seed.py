"""The curated brand-font catalog — seed source for ``seed_brand_fonts``.

Every entry ships a FULL fallback stack because the stack is the email/PDF
guarantee (email clients largely ignore webfonts). ``google_family`` is the
Google Fonts css2 family spec loaded by public web pages; "" marks a pure
system/email-safe stack that needs no webfont at all.

Curation rules:
- Keep the list small (~a dozen) — a brand kit is a choice, not a font browser.
- Every Google font pairs with a metric-compatible system fallback.
- Categories steer the pickers (headings want display faces, body wants text
  faces) but "both" entries appear in either picker.
"""

from __future__ import annotations

BRAND_FONT_CATALOG: list[dict] = [
    # --- Google fonts (webfont on public pages, stack in email/PDF) ---
    {
        "key": "poppins",
        "label": "Poppins",
        "category": "both",
        "css_stack": "'Poppins', 'Helvetica Neue', Arial, sans-serif",
        "google_family": "Poppins:wght@400;500;600;700",
        "sort_order": 10,
    },
    {
        "key": "inter",
        "label": "Inter",
        "category": "both",
        "css_stack": "'Inter', 'Helvetica Neue', Arial, sans-serif",
        "google_family": "Inter:wght@400;500;600;700",
        "sort_order": 20,
    },
    {
        "key": "nunito",
        "label": "Nunito",
        "category": "both",
        "css_stack": "'Nunito', 'Segoe UI', Verdana, sans-serif",
        "google_family": "Nunito:wght@400;600;700",
        "sort_order": 30,
    },
    {
        "key": "lora",
        "label": "Lora",
        "category": "both",
        "css_stack": "'Lora', Georgia, 'Times New Roman', serif",
        "google_family": "Lora:wght@400;500;600",
        "sort_order": 40,
    },
    {
        "key": "merriweather",
        "label": "Merriweather",
        "category": "both",
        "css_stack": "'Merriweather', Georgia, 'Times New Roman', serif",
        "google_family": "Merriweather:wght@400;700",
        "sort_order": 50,
    },
    {
        "key": "playfair-display",
        "label": "Playfair Display",
        "category": "heading",
        "css_stack": "'Playfair Display', Georgia, 'Times New Roman', serif",
        "google_family": "Playfair Display:wght@500;600;700",
        "sort_order": 60,
    },
    {
        "key": "source-serif",
        "label": "Source Serif 4",
        "category": "body",
        "css_stack": "'Source Serif 4', Georgia, 'Times New Roman', serif",
        "google_family": "Source Serif 4:wght@400;600",
        "sort_order": 70,
    },
    {
        "key": "work-sans",
        "label": "Work Sans",
        "category": "both",
        "css_stack": "'Work Sans', 'Helvetica Neue', Arial, sans-serif",
        "google_family": "Work Sans:wght@400;500;600",
        "sort_order": 80,
    },
    # --- Email-safe system stacks (no webfont anywhere) ---
    {
        "key": "georgia",
        "label": "Georgia",
        "category": "both",
        "css_stack": "Georgia, 'Times New Roman', serif",
        "google_family": "",
        "sort_order": 90,
    },
    {
        "key": "helvetica",
        "label": "Helvetica / Arial",
        "category": "both",
        "css_stack": "'Helvetica Neue', Helvetica, Arial, sans-serif",
        "google_family": "",
        "sort_order": 100,
    },
    {
        "key": "verdana",
        "label": "Verdana",
        "category": "body",
        "css_stack": "Verdana, Geneva, sans-serif",
        "google_family": "",
        "sort_order": 110,
    },
    {
        "key": "trebuchet",
        "label": "Trebuchet MS",
        "category": "both",
        "css_stack": "'Trebuchet MS', 'Segoe UI', sans-serif",
        "google_family": "",
        "sort_order": 120,
    },
]
