from __future__ import annotations


class ManagementCommandWorkspaceBootstrapFeedbackAdapter:
    def __init__(self, command):
        self._command = command

    def success(self, message: str) -> None:
        self._write("SUCCESS", message)

    def notice(self, message: str) -> None:
        self._write("NOTICE", message)

    def warning(self, message: str) -> None:
        self._write("WARNING", message)

    def _write(self, style_name: str, message: str) -> None:
        stdout = getattr(self._command, "stdout", None)
        style = getattr(self._command, "style", None)
        if stdout is None or style is None:
            return
        formatter = getattr(style, style_name, None)
        if formatter is None:
            return
        stdout.write(formatter(message))
