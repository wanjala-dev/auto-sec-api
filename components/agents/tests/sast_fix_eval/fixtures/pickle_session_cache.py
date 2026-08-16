"""Frozen corpus source — pickle over externally-sourced bytes (Class B)."""

import pickle


def restore_session(raw: bytes) -> dict:
    state = pickle.loads(raw)
    if not isinstance(state, dict):
        raise ValueError("session state must be a mapping")
    return state
