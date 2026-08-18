"""Workspace-derived names for the customer-side AWS audit artifacts.

Everything Auto-Sec asks a customer to create in THEIR account — the audit
role, its inline policy, the org StackSet — is named from the customer's own
workspace, not from us. Two reasons, both Henry's (2026-08-18, setting up the
Faura tenant):

1. The artifacts live in the customer's AWS account, so they should read as
   the customer's: ``FauraAuditRole`` tells a Faura admin exactly what it is;
   a vendor-branded name tells them to go ask someone.
2. Nothing hardcoded: a literal ``AutoSec*`` name in the generator meant every
   customer's account carried identical vendor-named IAM artifacts — a
   fingerprint, and a name collision the day one account connects two
   workspaces.

The ONE deliberate exception is the ``aws:ResourceTag/autosec`` condition key
on the CloudTrail-queue statement: that tag is the functional contract the
log-delivery setup instructs customers to apply, not a display name. Renaming
it per workspace would break every existing log source for zero gain.

IAM role names allow ``[A-Za-z0-9+=,.@_-]`` up to 64 chars; StackSet names are
stricter (alphanumeric + hyphens). We emit a conservative alphanumeric
CamelCase prefix that satisfies both, capped so the longest suffix still fits.

Framework-free: stdlib only.
"""

from __future__ import annotations

import re

#: Longest suffix we append is "AuditReadOnly" (13); IAM caps at 64. 32 keeps
#: names readable and leaves room without ever needing truncation logic twice.
_MAX_PREFIX = 32

_FALLBACK = "Workspace"


def role_name_prefix(workspace_name: str | None) -> str:
    """CamelCase alphanumeric prefix from a workspace name — ``"Faura"`` → ``"Faura"``,
    ``"faura security"`` → ``"FauraSecurity"``. Falls back to ``"Workspace"`` when the
    name sanitizes to nothing (emoji-only names exist)."""
    words = re.findall(r"[A-Za-z0-9]+", workspace_name or "")
    prefix = "".join(w[:1].upper() + w[1:] for w in words)[:_MAX_PREFIX]
    return prefix or _FALLBACK


def default_audit_role_name(workspace_name: str | None) -> str:
    """The default RoleName for a new connection: ``FauraAuditRole``."""
    return f"{role_name_prefix(workspace_name)}AuditRole"


def audit_policy_name(workspace_name: str | None) -> str:
    """The inline read-only policy name: ``FauraAuditReadOnly``."""
    return f"{role_name_prefix(workspace_name)}AuditReadOnly"


def stackset_name(workspace_name: str | None, connection_id) -> str:
    """Org-wide StackSet name: ``faura-audit-1a2b3c4d`` (StackSet charset is
    alphanumeric + hyphens; lowercase reads as infra, which a StackSet is)."""
    slug = role_name_prefix(workspace_name).lower()
    return f"{slug}-audit-{str(connection_id)[:8]}"


def external_id_prefix(workspace_name: str | None) -> str:
    """Lowercase slug prefixing the vendor-generated external id, so the value a
    customer pastes into their trust policy reads as theirs (``faura-<token>``).
    The token supplies all the entropy; the prefix is legibility."""
    slug = re.sub(r"[^a-z0-9]+", "-", (workspace_name or "").lower()).strip("-")[:20]
    return slug or "tenant"
