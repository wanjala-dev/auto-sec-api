"""Tenant utilities - simple utilities for host/tenant resolution."""


def hostname_from_request(request):
    """Extract the hostname from the request, removing port."""
    return request.get_host().split(":")[0].lower()
