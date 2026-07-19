from __future__ import annotations

import json
from typing import Any


def parse_bitpay_event(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize a BitPay webhook payload by returning the invoice data and parsed metadata."""
    event = payload.get("event") or {}
    invoice = event.get("data") or payload.get("data") or payload
    metadata_raw = invoice.get("posData") or invoice.get("pos_data")
    metadata: dict[str, Any] = {}
    if isinstance(metadata_raw, str):
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            metadata = {}
    elif isinstance(metadata_raw, dict):
        metadata = metadata_raw
    return invoice, metadata
