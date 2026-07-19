"""Unit tests for ProjectProvider composition root.

Tests provider factory methods and use case building.
Pure unit tests with mocked infrastructure dependencies.
"""

from unittest.mock import Mock, patch
from components.project.application.providers.project_provider import ProjectProvider
from components.project.application.use_cases.create_project_use_case import (
    CreateProjectUseCase,
)
from components.project.application.use_cases.create_task_use_case import (
    CreateTaskUseCase,
)
from components.project.application.use_cases.update_task_use_case import (
    UpdateTaskUseCase,
)


class TestProjectProviderStaticMethods:
    """Test that provider methods are static."""

    def test_provider_methods_are_static(self):
        """Provider methods should be callable as static methods (no self required)."""
        # Callable without instantiation
        assert callable(ProjectProvider.build_create_project_use_case)
        assert callable(ProjectProvider.build_create_task_use_case)
        assert callable(ProjectProvider.build_update_task_use_case)
        # Verify they're defined as staticmethod in the class dict
        for name in ("build_create_project_use_case", "build_create_task_use_case", "build_update_task_use_case"):
            assert isinstance(ProjectProvider.__dict__[name], staticmethod)


class TestProjectProviderBuildCreateProjectUseCase:
    """Test ProjectProvider.build_create_project_use_case()."""

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_build_create_project_use_case_returns_use_case(self, mock_repo_class):
        """build_create_project_use_case should return CreateProjectUseCase."""
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        use_case = ProjectProvider.build_create_project_use_case()

        assert isinstance(use_case, CreateProjectUseCase)

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_build_create_project_use_case_injects_repository_as_port(
        self, mock_repo_class
    ):
        """build_create_project_use_case should inject repository as port."""
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        use_case = ProjectProvider.build_create_project_use_case()

        # The port should be the repository instance
        assert use_case._port is mock_repo_instance

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_build_create_project_use_case_instantiates_repository(
        self, mock_repo_class
    ):
        """build_create_project_use_case should instantiate repository."""
        use_case = ProjectProvider.build_create_project_use_case()

        # Repository class should be instantiated
        mock_repo_class.assert_called_once()

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_build_create_project_use_case_multiple_calls_create_new_instances(
        self, mock_repo_class
    ):
        """Multiple calls should create new use case instances."""
        mock_repo_class.side_effect = [Mock(), Mock()]

        uc1 = ProjectProvider.build_create_project_use_case()
        uc2 = ProjectProvider.build_create_project_use_case()

        # Should be different instances
        assert uc1 is not uc2
        # Repository should be instantiated twice
        assert mock_repo_class.call_count == 2


class TestProjectProviderBuildCreateTaskUseCase:
    """Test ProjectProvider.build_create_task_use_case()."""

    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    def test_build_create_task_use_case_returns_use_case(self, mock_repo_class):
        """build_create_task_use_case should return CreateTaskUseCase."""
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        use_case = ProjectProvider.build_create_task_use_case()

        assert isinstance(use_case, CreateTaskUseCase)

    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    def test_build_create_task_use_case_injects_repository_as_port(
        self, mock_repo_class
    ):
        """build_create_task_use_case should inject repository as port."""
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        use_case = ProjectProvider.build_create_task_use_case()

        # The port should be the repository instance
        assert use_case._port is mock_repo_instance

    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    def test_build_create_task_use_case_instantiates_repository(self, mock_repo_class):
        """build_create_task_use_case should instantiate repository."""
        use_case = ProjectProvider.build_create_task_use_case()

        # Repository class should be instantiated
        mock_repo_class.assert_called_once()

    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    def test_build_create_task_use_case_multiple_calls_create_new_instances(
        self, mock_repo_class
    ):
        """Multiple calls should create new use case instances."""
        mock_repo_class.side_effect = [Mock(), Mock()]

        uc1 = ProjectProvider.build_create_task_use_case()
        uc2 = ProjectProvider.build_create_task_use_case()

        # Should be different instances
        assert uc1 is not uc2
        # Repository should be instantiated twice
        assert mock_repo_class.call_count == 2


class TestProjectProviderBuildUpdateTaskUseCase:
    """Test ProjectProvider.build_update_task_use_case()."""

    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_build_update_task_use_case_returns_use_case(self, mock_repo_class):
        """build_update_task_use_case should return UpdateTaskUseCase."""
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        use_case = ProjectProvider.build_update_task_use_case()

        assert isinstance(use_case, UpdateTaskUseCase)

    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_build_update_task_use_case_injects_repository_as_port(
        self, mock_repo_class
    ):
        """build_update_task_use_case should inject repository as port."""
        mock_repo_instance = Mock()
        mock_repo_class.return_value = mock_repo_instance

        use_case = ProjectProvider.build_update_task_use_case()

        # The port should be the repository instance
        assert use_case._port is mock_repo_instance

    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_build_update_task_use_case_instantiates_repository(self, mock_repo_class):
        """build_update_task_use_case should instantiate repository."""
        use_case = ProjectProvider.build_update_task_use_case()

        # Repository class should be instantiated
        mock_repo_class.assert_called_once()

    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_build_update_task_use_case_multiple_calls_create_new_instances(
        self, mock_repo_class
    ):
        """Multiple calls should create new use case instances."""
        mock_repo_class.side_effect = [Mock(), Mock()]

        uc1 = ProjectProvider.build_update_task_use_case()
        uc2 = ProjectProvider.build_update_task_use_case()

        # Should be different instances
        assert uc1 is not uc2
        # Repository should be instantiated twice
        assert mock_repo_class.call_count == 2


class TestProjectProviderComposition:
    """Test provider composition of use cases."""

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_provider_builds_all_use_cases(
        self, mock_update_repo, mock_create_task_repo, mock_create_proj_repo
    ):
        """Provider should build all three use cases."""
        mock_create_proj_repo.return_value = Mock()
        mock_create_task_repo.return_value = Mock()
        mock_update_repo.return_value = Mock()

        uc_create_proj = ProjectProvider.build_create_project_use_case()
        uc_create_task = ProjectProvider.build_create_task_use_case()
        uc_update_task = ProjectProvider.build_update_task_use_case()

        assert isinstance(uc_create_proj, CreateProjectUseCase)
        assert isinstance(uc_create_task, CreateTaskUseCase)
        assert isinstance(uc_update_task, UpdateTaskUseCase)

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_provider_uses_different_repositories_for_different_use_cases(
        self, mock_update_repo, mock_create_task_repo, mock_create_proj_repo
    ):
        """Provider should use appropriate repository for each use case."""
        proj_repo = Mock()
        task_repo = Mock()
        update_repo = Mock()

        mock_create_proj_repo.return_value = proj_repo
        mock_create_task_repo.return_value = task_repo
        mock_update_repo.return_value = update_repo

        uc_create_proj = ProjectProvider.build_create_project_use_case()
        uc_create_task = ProjectProvider.build_create_task_use_case()
        uc_update_task = ProjectProvider.build_update_task_use_case()

        # Each use case should have its own repository
        assert uc_create_proj._port is proj_repo
        assert uc_create_task._port is task_repo
        assert uc_update_task._port is update_repo

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_provider_use_cases_are_independent(
        self, mock_update_repo, mock_create_task_repo, mock_create_proj_repo
    ):
        """Use cases from provider should be independent."""
        mock_create_proj_repo.return_value = Mock()
        mock_create_task_repo.return_value = Mock()
        mock_update_repo.return_value = Mock()

        uc_create_proj = ProjectProvider.build_create_project_use_case()
        uc_create_task = ProjectProvider.build_create_task_use_case()
        uc_update_task = ProjectProvider.build_update_task_use_case()

        # Ports should all be different
        assert uc_create_proj._port is not uc_create_task._port
        assert uc_create_task._port is not uc_update_task._port
        assert uc_create_proj._port is not uc_update_task._port


class TestProjectProviderLazyImports:
    """Test that provider uses lazy imports for repositories."""

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_create_project_repository_imported_on_demand(self, mock_repo_class):
        """OrmCreateProjectRepository should be imported when building use case."""
        mock_repo_class.return_value = Mock()

        # Before calling build, no import yet (it's lazy)
        # After calling build, it should be imported
        ProjectProvider.build_create_project_use_case()

        # Repository class should be used
        mock_repo_class.assert_called_once()

    @patch(
        "components.project.infrastructure.repositories.create_task_repository.OrmCreateTaskRepository"
    )
    def test_create_task_repository_imported_on_demand(self, mock_repo_class):
        """OrmCreateTaskRepository should be imported when building use case."""
        mock_repo_class.return_value = Mock()

        ProjectProvider.build_create_task_use_case()

        # Repository class should be used
        mock_repo_class.assert_called_once()

    @patch(
        "components.project.infrastructure.repositories.update_task_repository.OrmUpdateTaskRepository"
    )
    def test_update_task_repository_imported_on_demand(self, mock_repo_class):
        """OrmUpdateTaskRepository should be imported when building use case."""
        mock_repo_class.return_value = Mock()

        ProjectProvider.build_update_task_use_case()

        # Repository class should be used
        mock_repo_class.assert_called_once()


class TestProjectProviderFactoryPattern:
    """Test that provider implements factory pattern correctly."""

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_provider_acts_as_factory(self, mock_repo_class):
        """Provider should act as factory for creating use cases."""
        mock_repo_class.return_value = Mock()

        # Factory should create new instance each time
        uc1 = ProjectProvider.build_create_project_use_case()
        uc2 = ProjectProvider.build_create_project_use_case()

        assert uc1 is not uc2

    @patch(
        "components.project.infrastructure.repositories.create_project_repository.OrmCreateProjectRepository"
    )
    def test_provider_factory_is_repeatable(self, mock_repo_class):
        """Provider factory should be repeatable and consistent."""
        mock_repo_class.side_effect = [Mock() for _ in range(5)]

        # Should be able to call multiple times
        use_cases = [
            ProjectProvider.build_create_project_use_case() for _ in range(5)
        ]

        assert len(use_cases) == 5
        # All should be different instances
        for i in range(len(use_cases)):
            for j in range(i + 1, len(use_cases)):
                assert use_cases[i] is not use_cases[j]
