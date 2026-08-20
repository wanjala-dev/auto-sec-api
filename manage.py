#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings.local")
    try:
        from django.core.management import execute_from_command_line  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Bind the pooled tenant for the whole command run. A command has no host
    # and no URL, so without this every one of the ~99 of them would be an
    # unbound path once the router is registered. Binding here rather than in a
    # base class each command must remember to inherit means there is nothing
    # to forget. The WORKSPACE is deliberately left unbound.
    #
    # Pooled stays the DEFAULT; `--tenant <subdomain>` / `--all-tenants` are
    # consumed here (never by the command) to reach a dedicated tenant's own
    # database — see
    # components/shared_platform/infrastructure/tenancy/management.py.
    from components.shared_platform.infrastructure.tenancy.management import (
        run_management_command,
    )

    run_management_command(sys.argv)


if __name__ == "__main__":
    main()
