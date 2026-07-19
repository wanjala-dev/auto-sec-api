"""Shared CSV reader utility — lives in the shared platform layer.

No business logic. Just reads CSV content into normalized dicts.
Any bounded context can import and use this.
"""
from __future__ import annotations

import csv
import io
import re


def read_csv_to_dicts(file_content: str | bytes) -> list[dict[str, str]]:
    """Parse raw CSV content into a list of dicts (header → value).

    Handles:
      - UTF-8 BOM
      - Whitespace stripping on keys and values
      - Empty rows skipped
    """
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(file_content))
    rows = []
    for row in reader:
        cleaned = {
            (k or "").strip(): (v or "").strip()
            for k, v in row.items()
            if k is not None
        }
        if any(v for v in cleaned.values()):
            rows.append(cleaned)
    return rows


def normalize_column_name(raw: str, aliases: dict[str, str] | None = None) -> str:
    """Normalize a CSV header to a canonical field name.

    Lowercases, replaces non-alphanum with underscores,
    then looks up in the aliases dict if provided.
    """
    cleaned = re.sub(r"[^a-z0-9_]", "_", raw.strip().lower())
    if aliases:
        return aliases.get(cleaned, cleaned)
    return cleaned
