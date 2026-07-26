from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from infrastructure.persistence.notifications.models import Notification
from components.notifications.infrastructure.adapters.notification_service import resolve_actor, sanitize_metadata

PREVIOUS_STATE_ATTR = "_notification_prev_state"
DELETE_RECIPIENTS_ATTR = "_notification_delete_recipients"
DELETE_WORKSPACE_ATTR = "_notification_delete_workspace"


@dataclass
class NotificationRule:
    model: type[models.Model]
    namespace: str
    workspace_getter: Callable[[models.Model], object | None]
    label_getter: Callable[[models.Model], str]
    recipients_getter: Callable[[models.Model], Iterable]
    base_events: tuple[str, ...] = ("created", "updated", "deleted")
    field_event_map: dict[str, str] = field(default_factory=dict)
    verb_templates: dict[str, str] = field(default_factory=dict)
    metadata_builder: Callable[[models.Model, str, dict], dict] | None = None
    tracked_fields: tuple[str, ...] = ()
    notification_type: str = Notification.NotificationType.SYSTEM
    include_default_metadata: bool = True

    def __post_init__(self):
        self.base_event_map = {
            suffix: f"{self.namespace}.{suffix}"
            for suffix in self.base_events
        }
        self.field_event_map = {
            field: f"{self.namespace}.{event}"
            for field, event in self.field_event_map.items()
        }
        tracked = set(self.tracked_fields)
        tracked.update(self.field_event_map.keys())
        self.tracked_fields = tuple(tracked)

    def event_name(self, suffix: str) -> str | None:
        return self.base_event_map.get(suffix)

    def build_verb(self, instance, event_name: str, changes: dict) -> str:
        label = self.label_getter(instance)
        context = {
            "label": label,
            "model": instance._meta.verbose_name.title(),
        }
        for field, payload in changes.items():
            context[field] = sanitize_metadata(payload.get("current"))
            context[f"{field}_previous"] = sanitize_metadata(payload.get("previous"))

        template = self.verb_templates.get(event_name)
        if template:
            try:
                return template.format(**context)
            except KeyError:
                pass

        action = event_name.split(".")[-1].replace("_", " ")
        return f'{action.capitalize()} {context["model"]} "{label}"'

    def build_metadata(self, instance, event_name: str, changes: dict) -> dict:
        metadata = {}
        if self.include_default_metadata:
            metadata.update(
                {
                    "event": event_name,
                    "model": instance._meta.label_lower,
                    "label": self.label_getter(instance),
                    "changed": {
                        field: {
                            "previous": sanitize_metadata(payload.get("previous")),
                            "current": sanitize_metadata(payload.get("current")),
                        }
                        for field, payload in changes.items()
                    },
                }
            )
        if self.metadata_builder:
            extra = self.metadata_builder(instance, event_name, changes) or {}
            metadata.update(extra)
        return metadata


class DjangoModelNotificationRegistry:
    def __init__(self, rule_service):
        self._rules: dict[type[models.Model], NotificationRule] = {}
        self.rule_service = rule_service

    def register(self, rule: NotificationRule):
        model = rule.model
        if model in self._rules:
            return
        self._rules[model] = rule

        if rule.tracked_fields:
            pre_save.connect(
                self._capture_previous_state(rule),
                sender=model,
                weak=False,
                dispatch_uid=self._uid(model, "capture"),
            )

        if rule.event_name("deleted"):
            pre_delete.connect(
                self._capture_delete_context(rule),
                sender=model,
                weak=False,
                dispatch_uid=self._uid(model, "pre_delete"),
            )
            post_delete.connect(
                self._handle_delete(rule),
                sender=model,
                weak=False,
                dispatch_uid=self._uid(model, "post_delete"),
            )

        post_save.connect(
            self._handle_save(rule),
            sender=model,
            weak=False,
            dispatch_uid=self._uid(model, "post_save"),
        )

    def _uid(self, model, suffix: str) -> str:
        return f"notifications:{model._meta.label_lower}:{suffix}"

    def _capture_previous_state(self, rule: NotificationRule):
        def handler(sender, instance, **kwargs):
            if not getattr(instance, "pk", None):
                return
            try:
                previous = sender.objects.get(pk=instance.pk)
            except sender.DoesNotExist:
                return
            setattr(
                instance,
                PREVIOUS_STATE_ATTR,
                {field: getattr(previous, field, None) for field in rule.tracked_fields},
            )

        return handler

    def _capture_delete_context(self, rule: NotificationRule):
        def handler(sender, instance, **kwargs):
            setattr(instance, DELETE_WORKSPACE_ATTR, rule.workspace_getter(instance))
            setattr(instance, DELETE_RECIPIENTS_ATTR, list(rule.recipients_getter(instance)))

        return handler

    def _handle_save(self, rule: NotificationRule):
        def handler(sender, instance, created, update_fields=None, **kwargs):
            workspace = rule.workspace_getter(instance)
            recipients = list(rule.recipients_getter(instance))
            actor = resolve_actor(instance)
            previous_state = getattr(instance, PREVIOUS_STATE_ATTR, None) or {}
            try:
                self.rule_service.process_save(
                    rule=rule,
                    instance=instance,
                    actor=actor,
                    workspace=workspace,
                    recipients=recipients,
                    created=created,
                    update_fields=set(update_fields) if update_fields else None,
                    previous_state=previous_state,
                )
            finally:
                if hasattr(instance, PREVIOUS_STATE_ATTR):
                    delattr(instance, PREVIOUS_STATE_ATTR)

        return handler

    def _handle_delete(self, rule: NotificationRule):
        def handler(sender, instance, **kwargs):
            event_name = rule.event_name("deleted")
            if not event_name:
                return

            workspace = getattr(instance, DELETE_WORKSPACE_ATTR, None) or rule.workspace_getter(instance)
            recipients = getattr(instance, DELETE_RECIPIENTS_ATTR, None) or list(
                rule.recipients_getter(instance)
            )
            actor = resolve_actor(instance)
            self.rule_service.process_delete(
                rule=rule,
                instance=instance,
                actor=actor,
                workspace=workspace,
                recipients=recipients,
            )

            for attr in (DELETE_WORKSPACE_ATTR, DELETE_RECIPIENTS_ATTR):
                if hasattr(instance, attr):
                    delattr(instance, attr)

        return handler
