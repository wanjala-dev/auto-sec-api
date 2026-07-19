from types import SimpleNamespace

from components.shared_kernel.application.model_notification_rule_service import (
    ModelNotificationRuleService,
)


class _FakeDispatchPort:
    def __init__(self) -> None:
        self.calls = []

    def dispatch(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _FakeRule:
    notification_type = "system"

    def __init__(self) -> None:
        self.field_event_map = {"status": "items.status_changed"}

    def event_name(self, suffix: str) -> str | None:
        return {
            "created": "items.created",
            "updated": "items.updated",
            "deleted": "items.deleted",
        }.get(suffix)

    def build_verb(self, instance, event_name: str, changes: dict) -> str:
        return f"{event_name}:{instance.label}"

    def build_metadata(self, instance, event_name: str, changes: dict) -> dict:
        return {"event": event_name, "changed": changes}


def test_process_save_dispatches_base_update_when_non_field_specific_changes_exist():
    port = _FakeDispatchPort()
    service = ModelNotificationRuleService(notification_dispatch_port=port)
    rule = _FakeRule()
    instance = SimpleNamespace(label="Item", status="active", title="New")

    service.process_save(
        rule=rule,
        instance=instance,
        actor=object(),
        workspace=object(),
        recipients=[object()],
        created=False,
        previous_state={"status": "draft", "title": "Old"},
    )

    assert [call["metadata"]["event"] for call in port.calls] == [
        "items.updated",
        "items.status_changed",
    ]


def test_process_save_skips_base_update_when_only_field_specific_changes_exist():
    port = _FakeDispatchPort()
    service = ModelNotificationRuleService(notification_dispatch_port=port)
    rule = _FakeRule()
    instance = SimpleNamespace(label="Item", status="active")

    service.process_save(
        rule=rule,
        instance=instance,
        actor=object(),
        workspace=object(),
        recipients=[object()],
        created=False,
        previous_state={"status": "draft"},
    )

    assert [call["metadata"]["event"] for call in port.calls] == [
        "items.status_changed",
    ]


def test_process_delete_dispatches_deleted_event():
    port = _FakeDispatchPort()
    service = ModelNotificationRuleService(notification_dispatch_port=port)
    rule = _FakeRule()
    instance = SimpleNamespace(label="Item")

    service.process_delete(
        rule=rule,
        instance=instance,
        actor=object(),
        workspace=object(),
        recipients=[object()],
    )

    assert [call["metadata"]["event"] for call in port.calls] == ["items.deleted"]
