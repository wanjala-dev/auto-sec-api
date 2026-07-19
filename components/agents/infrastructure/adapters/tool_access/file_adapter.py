"""File-based tool access adapter.

Delegates tool operations to local filesystem reads/writes.
This is the adapter for tools whose ``access_strategy`` is
``ToolAccessStrategy.FILE``.

The ``access_config`` on the Tool AR specifies allowed paths::

    access_config = {
        "allowed_paths": ["/data/exports/", "/data/uploads/"],
        "formats": ["csv", "json", "txt"],
        "max_file_size_mb": 50,
    }
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from components.agents.application.ports.tool_access_port import ToolAccessPort

logger = logging.getLogger(__name__)


class FileToolAccessAdapter(ToolAccessPort):
    """Executes tool operations via filesystem access."""

    def execute(
        self,
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> Any:
        allowed_paths = access_config.get("allowed_paths", [])
        file_path = params.get("file_path", "")

        if not file_path:
            raise ValueError("File operations require a 'file_path' parameter")

        self._validate_path(file_path, allowed_paths)

        if operation == "read":
            return self._read_file(file_path, access_config)
        elif operation == "list":
            return self._list_files(file_path, access_config)
        elif operation == "write":
            content = params.get("content", "")
            return self._write_file(file_path, content, access_config)
        else:
            raise ValueError(f"Unsupported file operation: {operation!r}")

    def supports_operation(self, operation: str) -> bool:
        return operation in ("read", "list", "write")

    def list_operations(self) -> List[str]:
        return ["read", "list", "write"]

    def health_check(self, access_config: Dict[str, Any]) -> bool:
        allowed_paths = access_config.get("allowed_paths", [])
        return all(os.path.exists(p) for p in allowed_paths)

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _validate_path(file_path: str, allowed_paths: List[str]) -> None:
        """Ensure the file path falls within an allowed directory."""
        if not allowed_paths:
            raise PermissionError("No allowed paths configured for file access")
        resolved = str(Path(file_path).resolve())
        for allowed in allowed_paths:
            if resolved.startswith(str(Path(allowed).resolve())):
                return
        raise PermissionError(
            f"Path {file_path!r} is outside allowed directories"
        )

    @staticmethod
    def _read_file(
        file_path: str, access_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        max_size_mb = access_config.get("max_file_size_mb", 50)
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            raise ValueError(
                f"File exceeds size limit ({size_mb:.1f}MB > {max_size_mb}MB)"
            )

        suffix = path.suffix.lower()
        content = path.read_text(encoding="utf-8")

        if suffix == ".json":
            return {"format": "json", "data": json.loads(content)}
        elif suffix == ".csv":
            return {"format": "csv", "data": content, "rows": content.count("\n")}
        else:
            return {"format": "text", "data": content}

    @staticmethod
    def _list_files(
        dir_path: str, access_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        allowed_formats = access_config.get("formats", [])
        path = Path(dir_path)
        if not path.is_dir():
            raise ValueError(f"Not a directory: {dir_path}")

        files = []
        for entry in sorted(path.iterdir()):
            if not entry.is_file():
                continue
            if allowed_formats and entry.suffix.lstrip(".") not in allowed_formats:
                continue
            files.append({
                "name": entry.name,
                "size_bytes": entry.stat().st_size,
                "modified": entry.stat().st_mtime,
            })
        return files

    @staticmethod
    def _write_file(
        file_path: str, content: str, access_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path), "size_bytes": path.stat().st_size}
