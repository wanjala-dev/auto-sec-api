from __future__ import annotations

from django.db.models.signals import m2m_changed


class TaskAssignmentSignalAdapter:
    def connect(self, *, task_model, use_case, actor_resolver) -> None:
        m2m_changed.connect(
            self._build_handler(use_case=use_case, actor_resolver=actor_resolver),
            sender=task_model.assigned_to.through,
            weak=False,
            dispatch_uid="notifications:tasks:assignment",
        )

    @staticmethod
    def _build_handler(*, use_case, actor_resolver):
        def receiver(sender, instance, action, pk_set, **kwargs):
            if action not in ("post_add", "post_remove") or not pk_set:
                return

            actor = actor_resolver(instance)
            use_case.execute(
                task=instance,
                actor=actor,
                recipient_ids=pk_set,
                action=action,
            )

        return receiver
