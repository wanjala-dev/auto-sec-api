"""Composition root for project/task operations in the project bounded context."""

from __future__ import annotations

from components.project.application.use_cases.archive_finding_cards_use_case import ArchiveFindingCardsUseCase
from components.project.application.use_cases.mark_finding_draft_pr_rejected_use_case import (
    MarkFindingDraftPrRejectedUseCase,
)
from components.project.application.use_cases.attach_finding_draft_pr_patch_use_case import (
    AttachFindingDraftPrPatchUseCase,
)
from components.project.application.use_cases.batch_move_tasks_use_case import BatchMoveTasksUseCase
from components.project.application.use_cases.create_project_use_case import CreateProjectUseCase
from components.project.application.use_cases.create_task_use_case import CreateTaskUseCase
from components.project.application.use_cases.move_task_to_board_use_case import MoveTaskToBoardUseCase
from components.project.application.use_cases.record_finding_draft_pr_use_case import RecordFindingDraftPrUseCase
from components.project.application.use_cases.record_finding_preview_use_case import RecordFindingPreviewUseCase
from components.project.application.use_cases.resolve_finding_task_use_case import ResolveFindingTaskUseCase
from components.project.application.use_cases.update_task_use_case import UpdateTaskUseCase


class ProjectProvider:
    @staticmethod
    def build_create_task_use_case() -> CreateTaskUseCase:
        from components.project.infrastructure.repositories.create_task_repository import (
            OrmCreateTaskRepository,
        )

        return CreateTaskUseCase(port=OrmCreateTaskRepository())

    @staticmethod
    def build_create_project_use_case() -> CreateProjectUseCase:
        from components.project.infrastructure.repositories.create_project_repository import (
            OrmCreateProjectRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return CreateProjectUseCase(
            port=OrmCreateProjectRepository(),
            event_publisher=CeleryEventPublisher(),
        )

    @staticmethod
    def build_update_task_use_case() -> UpdateTaskUseCase:
        from components.project.infrastructure.repositories.update_task_repository import (
            OrmUpdateTaskRepository,
        )

        return UpdateTaskUseCase(port=OrmUpdateTaskRepository())

    @staticmethod
    def build_batch_move_tasks_use_case() -> BatchMoveTasksUseCase:
        from components.project.infrastructure.repositories.batch_move_tasks_repository import (
            OrmBatchMoveTasksRepository,
        )

        return BatchMoveTasksUseCase(port=OrmBatchMoveTasksRepository())

    @staticmethod
    def build_move_task_to_board_use_case() -> MoveTaskToBoardUseCase:
        from components.project.infrastructure.repositories.move_task_to_board_repository import (
            OrmMoveTaskToBoardRepository,
        )

        return MoveTaskToBoardUseCase(port=OrmMoveTaskToBoardRepository())

    @staticmethod
    def build_record_finding_draft_pr_use_case() -> RecordFindingDraftPrUseCase:
        from components.project.infrastructure.repositories.record_finding_draft_pr_repository import (
            OrmRecordFindingDraftPrRepository,
        )

        return RecordFindingDraftPrUseCase(port=OrmRecordFindingDraftPrRepository())

    @staticmethod
    def build_attach_finding_draft_pr_patch_use_case() -> AttachFindingDraftPrPatchUseCase:
        from components.project.infrastructure.repositories.record_finding_draft_pr_repository import (
            OrmRecordFindingDraftPrRepository,
        )

        return AttachFindingDraftPrPatchUseCase(port=OrmRecordFindingDraftPrRepository())

    @staticmethod
    def build_mark_finding_draft_pr_rejected_use_case() -> MarkFindingDraftPrRejectedUseCase:
        from components.project.infrastructure.repositories.record_finding_draft_pr_repository import (
            OrmRecordFindingDraftPrRepository,
        )

        return MarkFindingDraftPrRejectedUseCase(port=OrmRecordFindingDraftPrRepository())

    @staticmethod
    def build_record_finding_preview_use_case() -> RecordFindingPreviewUseCase:
        from components.project.infrastructure.repositories.record_finding_preview_repository import (
            OrmRecordFindingPreviewRepository,
        )

        return RecordFindingPreviewUseCase(port=OrmRecordFindingPreviewRepository())

    @staticmethod
    def build_task_lookup_port() -> TaskLookupPort:
        from components.project.infrastructure.repositories.task_lookup_repository import (
            OrmTaskLookupRepository,
        )

        return OrmTaskLookupRepository()

    @staticmethod
    def build_posture_facts_port() -> PostureFactsPort:
        from components.project.infrastructure.repositories.posture_facts_repository import (
            OrmPostureFactsRepository,
        )

        return OrmPostureFactsRepository()

    @staticmethod
    def build_resolve_finding_task_use_case() -> ResolveFindingTaskUseCase:
        from components.project.infrastructure.repositories.resolve_finding_task_repository import (
            OrmResolveFindingTaskRepository,
        )

        return ResolveFindingTaskUseCase(port=OrmResolveFindingTaskRepository())

    @staticmethod
    def build_archive_finding_cards_use_case() -> ArchiveFindingCardsUseCase:
        """The suppressed-finding card archive write (recycle-bin tombstone,
        never a delete) — driven by the agents ``FindingResolved`` board handler
        and the ``archive_suppressed_finding_cards`` backfill command."""
        from components.project.infrastructure.repositories.archive_finding_cards_repository import (
            OrmArchiveFindingCardsRepository,
        )

        return ArchiveFindingCardsUseCase(port=OrmArchiveFindingCardsRepository())
