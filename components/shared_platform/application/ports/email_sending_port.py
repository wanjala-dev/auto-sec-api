"""Port for sending emails — application layer stays provider-free.

Any email backend (Django SMTP, SendGrid, AWS SES, Postmark, …)
implements this contract so upper layers never couple to a specific SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmailMessage:
    """Technology-agnostic email payload."""

    subject: str
    to: list[str]
    text_body: str = ""
    html_body: str = ""
    from_email: str = ""
    reply_to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)


class EmailSendingPort(ABC):
    """Secondary/driven port for email dispatch."""

    @abstractmethod
    def send(self, message: EmailMessage) -> bool:
        """Send a single email.

        Returns True if the email was dispatched successfully.
        """
        ...

    @abstractmethod
    def send_templated(
        self,
        *,
        to: Sequence[str],
        subject: str,
        template: str,
        context: dict,
        from_email: str = "",
        workspace_id=None,
    ) -> bool:
        """Render *template* with *context* and send as HTML email.

        When *workspace_id* is provided, the workspace brand colours are
        resolved and merged into the render context (so the shared branded
        email base adopts the workspace brand). Returns True if the email
        was dispatched successfully.
        """
        ...
