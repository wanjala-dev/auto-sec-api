"""
Settings package entrypoint.

Use an explicit environment module (e.g., ``api.settings.local``, ``api.settings.dev``,
``api.settings.prod``, or ``api.settings.test``) instead of the package itself so we
do not silently merge multiple configuration files.
"""

import os

_settings_module = os.environ.get("DJANGO_SETTINGS_MODULE")

if _settings_module == "api.settings":
    raise RuntimeError(
        "DJANGO_SETTINGS_MODULE must point to a concrete module "
        "(api.settings.local|dev|prod|test)."
    )
