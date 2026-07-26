"""Derive a resource's exposure from the finding evidence we have today.

A deliberate heuristic over the Prowler check that flagged the resource: check ids /
resource types that name public/internet reachability mark the asset ``PUBLIC``. This is
the honest ceiling of the Prowler-derived substrate (spike §3, Option A) — a later
boto3/CloudQuery inventory adapter will set exposure from real network config (security
groups, route tables, public IPs) instead of a name match. Keep the marker list here so
that upgrade is a one-file change.
"""

from __future__ import annotations

from components.cloud_graph.domain.value_objects.enums import Exposure

_PUBLIC_MARKERS = (
    "public",
    "internet",
    "0.0.0.0",
    "exposed",
    "anonymous",
    "world",
    "unrestricted",
)


def classify_exposure(*, check_id: str = "", resource_type: str = "") -> Exposure:
    haystack = f"{check_id} {resource_type}".lower()
    if any(marker in haystack for marker in _PUBLIC_MARKERS):
        return Exposure.PUBLIC
    return Exposure.PRIVATE
