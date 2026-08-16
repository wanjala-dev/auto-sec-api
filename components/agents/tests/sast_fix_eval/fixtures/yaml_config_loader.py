"""Frozen corpus source — unsafe yaml load behind an ALIASED import (awkward case)."""

import yaml as y


def load_pipeline_config(raw: str) -> dict:
    parsed = y.load(raw)
    if not isinstance(parsed, dict):
        raise ValueError("pipeline config must be a mapping")
    return parsed
