"""Frozen corpus source — TLS verification disabled on an outbound call."""

import requests


def probe_webhook(url: str, payload: dict) -> int:
    response = requests.post(url, json=payload, timeout=10, verify=False)
    return response.status_code
