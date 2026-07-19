"""Composition-root smoke tests for SharedPlatformProvider.

Every ``build_*`` factory must construct without error. This exists because
a stripped import in the provider is invisible to use-case unit tests (they
inject fakes directly) and only explodes at REQUEST time as a NameError —
which is exactly what happened to build_confirm_presigned_upload_use_case
on prod (2026-07-12). ``from __future__ import annotations`` makes the
return annotations lazy, so only actually CALLING the factory catches it.
"""

from __future__ import annotations

import pytest

from components.shared_platform.application.providers.shared_platform_provider import (
    SharedPlatformProvider,
)


class TestSharedPlatformProviderComposition:
    @pytest.mark.parametrize(
        "factory_name",
        [name for name in dir(SharedPlatformProvider) if name.startswith("build_")],
    )
    def test_every_factory_constructs(self, factory_name):
        built = getattr(SharedPlatformProvider, factory_name)()
        assert built is not None
