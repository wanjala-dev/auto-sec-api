from components.shared_kernel.application.providers.default_notification_catalog_provider import (
    DefaultNotificationCatalogProvider,
)


def test_default_notification_catalog_provider_registers_defaults(monkeypatch):
    captured = {"count": 0}

    monkeypatch.setattr(
        "components.shared_kernel.application.providers.default_notification_catalog_provider.register_default_notification_rules",
        lambda: captured.__setitem__("count", captured["count"] + 1),
    )

    DefaultNotificationCatalogProvider().register_defaults()

    assert captured["count"] == 1
