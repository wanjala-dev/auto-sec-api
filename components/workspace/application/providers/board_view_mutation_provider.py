from __future__ import annotations

from components.workspace.application.use_cases.create_board_view_use_case import CreateBoardViewUseCase
from components.workspace.application.use_cases.delete_board_view_use_case import DeleteBoardViewUseCase
from components.workspace.application.use_cases.update_board_view_use_case import UpdateBoardViewUseCase
from components.workspace.infrastructure.repositories.board_view_mutation_repository import (
    OrmBoardViewMutationRepository,
)


class BoardViewMutationProvider:
    """Composition root for saved-view writes (task #74) — the mutation
    sibling of ``BoardViewQueryProvider``."""

    @staticmethod
    def build_create_view_use_case() -> CreateBoardViewUseCase:
        return CreateBoardViewUseCase(mutation_port=OrmBoardViewMutationRepository())

    @staticmethod
    def build_update_view_use_case() -> UpdateBoardViewUseCase:
        return UpdateBoardViewUseCase(mutation_port=OrmBoardViewMutationRepository())

    @staticmethod
    def build_delete_view_use_case() -> DeleteBoardViewUseCase:
        return DeleteBoardViewUseCase(mutation_port=OrmBoardViewMutationRepository())
