"""Request DTOs: create / update a VcsConnection (ADR 0010 Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field

_VALID_PROVIDERS = {"github", "gitlab", "bitbucket"}
# Providers with a shipped adapter, selectable via the API. GitLab/Bitbucket stay
# catalog-only (rejected here) until their adapters land, behind feature flags.
_ENABLED_PROVIDERS = {"github"}
# Statuses a workspace may set via the API. ``error`` is system-owned (set by verify);
# ``connected`` re-enables, ``disabled`` pauses a connection.
_VALID_STATUSES = {"connected", "disabled"}


def _clean_allowlist(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [r.strip() for r in raw if isinstance(r, str) and r.strip()]


def _repo_root_error(repo_root: str) -> str | None:
    """Reject a ``repo_root`` that could escape the repo-scoped GitHub URL.

    A monorepo subdirectory is a relative, forward-slash path (``api-v2.0`` or
    ``services/api``) — never absolute, never with ``.``/``..`` segments. An
    attacker-set ``../../../etc`` would interpolate into ``/repos/<repo>/contents/``
    and climb out of the repo (→ ``api.github.com/repos/etc/...``). Blank is fine
    (auto-detect). Returns an error string, or ``None`` when safe."""
    root = (repo_root or "").strip().replace("\\", "/")
    if not root:
        return None
    if root.startswith("/"):
        return "repo_root must be a relative path (no leading '/')."
    # A leading/trailing slash alone is harmless (normalized away); only '.'/'..'
    # segments can climb out of the repo-scoped URL.
    if any(seg in (".", "..") for seg in root.split("/")):
        return "repo_root must not contain '.' or '..' path segments."
    return None


@dataclass(frozen=True)
class CreateVcsConnectionRequest:
    """Validated input for ``POST /integrations/workspaces/<ws>/vcs-connections/``."""

    provider: str
    token: str
    name: str = ""
    base_url: str = ""
    repo_root: str = ""
    repo_allowlist: list = field(default_factory=list)

    @classmethod
    def from_payload(cls, data: dict) -> CreateVcsConnectionRequest:
        data = data or {}
        return cls(
            provider=str(data.get("provider") or "").strip().lower(),
            token=str(data.get("token") or "").strip(),
            name=str(data.get("name") or "").strip(),
            base_url=str(data.get("base_url") or "").strip(),
            repo_root=str(data.get("repo_root") or "").strip(),
            repo_allowlist=_clean_allowlist(data.get("repo_allowlist")),
        )

    def validation_error(self) -> str | None:
        if self.provider not in _VALID_PROVIDERS:
            return f"provider must be one of {sorted(_VALID_PROVIDERS)}."
        if self.provider not in _ENABLED_PROVIDERS:
            return f"The {self.provider} provider is not available yet."
        if not self.token:
            return "A token is required to create a VCS connection."
        return _repo_root_error(self.repo_root)


@dataclass(frozen=True)
class UpdateVcsConnectionRequest:
    """Partial update — only supplied fields are applied. ``None`` means 'leave as-is'."""

    name: str | None = None
    base_url: str | None = None
    repo_root: str | None = None
    status: str | None = None
    token: str | None = None
    repo_allowlist: list | None = None

    @classmethod
    def from_payload(cls, data: dict) -> UpdateVcsConnectionRequest:
        data = data or {}
        name = data.get("name")
        base_url = data.get("base_url")
        repo_root = data.get("repo_root")
        status = data.get("status")
        token = data.get("token")
        allowlist = data.get("repo_allowlist")
        return cls(
            name=None if name is None else str(name).strip(),
            base_url=None if base_url is None else str(base_url).strip(),
            repo_root=None if repo_root is None else str(repo_root).strip(),
            status=None if status is None else str(status).strip().lower(),
            token=None if token is None else str(token).strip(),
            repo_allowlist=None if allowlist is None else _clean_allowlist(allowlist),
        )

    def validation_error(self) -> str | None:
        if self.status is not None and self.status not in _VALID_STATUSES:
            return "status can only be set to 'connected' or 'disabled' via the API."
        if self.repo_root is not None:
            return _repo_root_error(self.repo_root)
        return None
