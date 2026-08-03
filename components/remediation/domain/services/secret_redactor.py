"""Secret redaction for fix-code before it lands in the retrievable corpus (ADR 0012 P6).

Defence-in-depth for D1/D3: the Remediation Memory corpus is a NEW place customer
code lands (embedded into ``ai_embedding_chunks`` and later surfaced to the triage
advisor as grounding). A vetted fix *should* never contain a live secret, but "should"
is not a control — so before a fix's code is embedded we run a light, pattern-based
scrub that redacts obvious credentials (API keys, bearer/JWT tokens, PEM private keys,
AWS keys, and ``secret =`` / ``password:`` style high-entropy assignments).

Framework-free pure function (a domain service): no Django, no I/O, no logging — it
takes a string and returns a redacted string. The CALLER must never log the raw or the
matched value (``logging.md`` §4): only a count/flag is safe to log. This is deliberately
conservative (favours a false-positive redaction over leaking a real secret) because the
blast radius of a leaked secret in a security product's shared corpus is severe.

Not a replacement for good hygiene at the source — a redacted token in the corpus still
means a token reached us; this is the last line, not the first.
"""

from __future__ import annotations

import re

# The placeholder a matched secret is replaced with. Distinctive + greppable so a
# redacted corpus entry is obvious in review, and carries no residue of the secret.
REDACTION_PLACEHOLDER = "«REDACTED-SECRET»"

# Each pattern targets a concrete, well-known credential shape. Ordered most-specific
# first; PEM blocks are handled before the line-oriented patterns so a multi-line key
# is collapsed as one unit. Every pattern redacts only the SECRET material — never the
# surrounding assignment key — so the fix stays readable ("api_key = «REDACTED-SECRET»").
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
    re.DOTALL,
)

# Discrete token shapes (each is a self-identifying prefix + body).
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),  # AWS temporary (STS) access key id
    re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),  # GitHub PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),  # GitHub fine-grained PAT
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack token
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),  # OpenAI-style secret key
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),  # Google API key
)

# ``key = "value"`` / ``key: value`` / ``"key": "value"`` assignments where the KEY names
# a secret. Captures the assignment head (key + optional closing quote + operator + optional
# opening quote) in group 1 so we keep it and redact only the value. The optional quote BEFORE
# the separator is what catches JSON/dict-shaped secrets — ``{"api_key": "…"}`` — whose ``"``
# between the key and the ``:`` otherwise breaks a bare ``\bkey\b\s*[:=]`` match. Value = a run
# of non-space/non-quote chars long enough to be a real secret (≥ 8), so short config words
# ("password: true") aren't clobbered wholesale.
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (
        \b(?:password|passwd|pwd|secret|secret_key|api[_-]?key|apikey|access[_-]?key|
        auth[_-]?token|access[_-]?token|refresh[_-]?token|client[_-]?secret|
        private[_-]?key|bearer|token)\b
        ['"]?\s*[:=]\s*
        ['"]?
    )
    ([^\s'"]{8,})
    """,
)

# Known residual gaps — ACCEPTED defence-in-depth limitations, not bugs (ADR 0012:
# "this is the last line, not the first"). This scrub is a conservative last-resort net
# over vetted fixes that should already be secret-free; it deliberately does NOT chase:
#   - Opaque bearer/authorization values with no self-identifying prefix or secret-named
#     key — e.g. ``Authorization: Bearer <opaque>`` where ``<opaque>`` is a bare
#     high-entropy blob. ``bearer``/``token`` keyed assignments ARE caught; a naked
#     ``Bearer xxxxx`` header value with no ``bearer =`` key is not, to avoid clobbering
#     ordinary prose/identifiers.
#   - Secrets split across lines (a value continued onto the next physical line, or a
#     token wrapped mid-string), which the single-line value class ``[^\s'"]{8,}`` will
#     only partially match.
# These are intentionally out of scope: over-broadening the value class to chase them
# risks redacting benign code, and the real control is source hygiene + the entry gate,
# not this regex. Tighten here only with a concrete leak this net missed.


def redact_secrets(text: str) -> tuple[str, int]:
    """Return ``(redacted_text, count)`` — *text* with obvious secrets replaced by
    :data:`REDACTION_PLACEHOLDER`, plus how many redactions were applied.

    Pure + side-effect-free. ``count`` lets the caller log that redaction happened
    WITHOUT ever logging the value (``logging.md`` §4). Empty/whitespace input is a
    no-op returning ``("", 0)`` / the original with ``0``.
    """
    if not text:
        return text or "", 0

    count = 0

    def _sub(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return REDACTION_PLACEHOLDER

    redacted = _PEM_PRIVATE_KEY.sub(_sub, text)
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(_sub, redacted)

    def _sub_assignment(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{REDACTION_PLACEHOLDER}"

    redacted = _SECRET_ASSIGNMENT.sub(_sub_assignment, redacted)
    return redacted, count
