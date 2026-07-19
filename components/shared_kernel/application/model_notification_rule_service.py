from __future__ import annotations

from components.shared_kernel.application.ports.model_notification_dispatch_port import (
    ModelNotificationDispatchPort,
)


class ModelNotificationRuleService:
    def __init__(
        self,
        *,
        notification_dispatch_port: ModelNotificationDispatchPort,
    ) -> None:
        self.notification_dispatch_port = notification_dispatch_port

    def process_save(
        self,
        *,
        rule,
        instance,
        actor,
        workspace,
        recipients,
        created: bool,
        update_fields: set | None = None,
        previous_state: dict | None = None,
    ) -> None:
        if not recipients or actor is None:
            return

        changes = self._extract_changes(
            instance=instance,
            previous_state=previous_state or {},
            update_fields=update_fields,
        )

        events = []
        if created:
            event_name = rule.event_name("created")
            if event_name:
                events.append((event_name, {}))
        else:
            event_name = rule.event_name("updated")
            only_field_specific_changes = (
                bool(changes)
                and set(changes.keys()).issubset(set(rule.field_event_map.keys()))
            )
            if event_name and not only_field_specific_changes:
                events.append((event_name, changes))
            for field, field_event_name in rule.field_event_map.items():
                if field in changes:
                    events.append((field_event_name, {field: changes[field]}))

        self._dispatch_events(
            rule=rule,
            instance=instance,
            actor=actor,
            workspace=workspace,
            recipients=recipients,
            events=events,
        )

    def process_delete(
        self,
        *,
        rule,
        instance,
        actor,
        workspace,
        recipients,
    ) -> None:
        event_name = rule.event_name("deleted")
        if not event_name or not recipients or actor is None:
            return

        self._dispatch_events(
            rule=rule,
            instance=instance,
            actor=actor,
            workspace=workspace,
            recipients=recipients,
            events=[(event_name, {})],
        )

    def _dispatch_events(
        self,
        *,
        rule,
        instance,
        actor,
        workspace,
        recipients,
        events,
    ) -> None:
        for event_name, payload in events:
            if not event_name:
                continue
            verb = rule.build_verb(instance, event_name, payload)
            metadata = rule.build_metadata(instance, event_name, payload)
            self.notification_dispatch_port.dispatch(
                actor=actor,
                workspace=workspace,
                verb=verb,
                notification_type=rule.notification_type,
                recipients=recipients,
                metadata=metadata,
                target=instance,
            )

    @staticmethod
    def _extract_changes(
        *,
        instance,
        previous_state: dict,
        update_fields: set | None,
    ) -> dict:
        changes = {}
        for field, previous_value in previous_state.items():
            if update_fields and field not in update_fields:
                continue
            current_value = getattr(instance, field, None)
            if current_value != previous_value:
                changes[field] = {
                    "previous": previous_value,
                    "current": current_value,
                }
        return changes
