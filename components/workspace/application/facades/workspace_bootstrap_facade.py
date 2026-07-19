from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from components.workspace.application.providers.workspace_bootstrap_provider import (
    WorkspaceBootstrapProvider,
)


class WorkspaceBootstrapConfigurationError(ValueError):
    """Raised when workspace bootstrap config input is invalid."""


class WorkspaceBootstrapFacade:
    """Cross-context entrypoint for workspace bootstrap orchestration.

    Accepts an optional ``bootstrap_defaults`` callable so the caller
    (typically a Django management command in the infrastructure layer)
    can inject the framework-specific bootstrapping step without this
    facade importing Django directly.
    """

    def execute(
        self,
        *,
        command,
        options,
        bootstrap_defaults: Callable[[], None] | None = None,
    ):
        configs = self._load_configs(options)

        if not options["skip_defaults"] and bootstrap_defaults is not None:
            bootstrap_defaults()

        use_case = WorkspaceBootstrapProvider().build_use_case(command=command)
        results = []
        for config in configs:
            results.append(
                use_case.execute(
                    config,
                    owner_email_override=options.get("owner_email"),
                    owner_password_override=options.get("owner_password"),
                )
            )
        return results

    def _load_configs(self, options) -> list[dict]:
        config_path = options.get("config")
        config_dir = options.get("config_dir")

        configs: list[dict] = []
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise WorkspaceBootstrapConfigurationError(f"Config file not found: {config_path}")
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["__config_dir"] = path.parent
            configs.append(data)
        elif config_dir:
            dir_path = Path(config_dir)
            if not dir_path.exists() or not dir_path.is_dir():
                raise WorkspaceBootstrapConfigurationError(
                    f"Config directory not found or not a directory: {config_dir}"
                )

            json_files: list[Path] = []
            json_files.extend(sorted(dir_path.glob("*.json")))

            for subdir in sorted(path for path in dir_path.iterdir() if path.is_dir()):
                config_file = subdir / "config.json"
                if config_file.exists():
                    json_files.append(config_file)
                    continue
                json_files.extend(sorted(subdir.glob("*.json")))

            if not json_files:
                raise WorkspaceBootstrapConfigurationError(
                    f"No JSON config files found in directory: {config_dir}"
                )

            for file_path in json_files:
                with file_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                data["__config_dir"] = file_path.parent
                configs.append(data)
        else:
            raise WorkspaceBootstrapConfigurationError(
                "Provide --config for one file or --config-dir for multiple files"
            )

        for config in configs:
            for section in ("owner", "workspace"):
                if section not in config:
                    raise WorkspaceBootstrapConfigurationError(
                        f"Config missing required section: '{section}'"
                    )

        return configs
