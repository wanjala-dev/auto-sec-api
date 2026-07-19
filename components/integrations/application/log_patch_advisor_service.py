"""Grounded patch generation for a triaged log-error finding.

Sibling of ``log_fix_advisor_service`` with the same discipline: the LLM runs
STRICTLY AFTER deterministic work, and every failure mode degrades to ``None``
— a finding that cannot yield a grounded patch simply doesn't get a draft PR.

Grounded + honest by construction:
- The candidate FILE PATH is derived deterministically from the finding's
  traceback/evidence (``File "/app/…"`` regex, then dotted-module → path)
  BEFORE the LLM is consulted. The LLM edits a file we fetched; it never
  invents paths.
- The model receives the CURRENT file content and must return STRICT JSON
  ``{"path", "updated_content", "change_summary"}`` — a full-file rewrite,
  which is verifiable, not a free-form diff.
- Groundedness gate (deterministic, zero LLM): the diff between old and new
  content must touch at least one line containing one of the finding's
  salient tokens (shared-kernel heuristic, the SAME anchors the agents-context
  grounded verifier uses). An unparseable, identical, oversized, or ungrounded
  result → ``None``.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass

from components.shared_kernel.utils.salient_tokens import salient_tokens

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4000
_TEMPERATURE = 0.1
# Files larger than this cannot be round-tripped safely through the model
# (truncation would silently mangle the committed file) — degrade to None.
_MAX_FILE_CHARS = 24_000

# Traceback frames: File "/app/components/x/y.py", line 12 — capture the
# repo-relative path. Also tolerates paths without the /app prefix.
_TRACEBACK_FILE_RE = re.compile(r'File "(?:/app/)?([\w./-]+\.py)"')
# Dotted module (components.foo.bar_baz) — converted to components/foo/bar_baz.py.
_DOTTED_MODULE_RE = re.compile(r"\b[a-z_][\w]*(?:\.[a-z_][\w]*){2,}\b")

_SYSTEM = (
    "You are a senior engineer producing a MINIMAL fix for one production "
    "error. You are given the error's evidence and the CURRENT full content "
    "of the implicated file. Respond with STRICT JSON and nothing else, "
    "shaped exactly:\n"
    '{"path": "<the file path you were given, unchanged>", '
    '"updated_content": "<the FULL corrected file content>", '
    '"change_summary": "<one sentence describing the change>"}\n'
    "Rules: change ONLY what the error evidence requires — no refactors, no "
    "reformatting, no unrelated edits. Preserve the file's existing style. "
    "If the evidence is insufficient to justify a concrete change, return "
    'exactly {"path": "", "updated_content": "", "change_summary": ""}. '
    "No preamble, no markdown, JSON only."
)


@dataclass(frozen=True)
class PatchProposal:
    path: str
    updated_content: str
    change_summary: str

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "updated_content": self.updated_content,
            "change_summary": self.change_summary,
        }


def derive_candidate_path(payload: dict) -> str | None:
    """Deterministically derive the implicated file path from the evidence.

    Priority: an explicit traceback ``File "…"`` frame (last frame wins — the
    deepest frame is where the error raised), then a dotted-module → path
    conversion (longest module wins). Returns ``None`` when the evidence names
    no file — no path, no patch, no PR.
    """
    parts = [str(payload.get("message") or ""), str(payload.get("signal") or "")]
    for ev in payload.get("evidence") or []:
        if isinstance(ev, dict):
            parts.append(str(ev.get("detail") or ""))
    text = "\n".join(parts)

    frames = _TRACEBACK_FILE_RE.findall(text)
    if frames:
        return frames[-1]

    # Dotted-module fallback — exclude hostname-shaped candidates (log lines
    # are full of s3.amazonaws.com-style hosts that are not Python modules).
    _HOST_SEGMENTS = {"com", "net", "org", "io", "www", "amazonaws", "localhost"}
    modules = [
        m for m in _DOTTED_MODULE_RE.findall(text) if not m.endswith(".py") and not (_HOST_SEGMENTS & set(m.split(".")))
    ]
    if modules:
        longest = max(modules, key=lambda m: m.count("."))
        return longest.replace(".", "/") + ".py"
    return None


class LogPatchAdvisor:
    """Turns one triaged finding + the implicated file into a grounded patch."""

    def __init__(self, llm_port=None) -> None:
        # Lazy — only resolve an LLM when actually asked, so importing this
        # module never forces the knowledge stack to load.
        self._llm = llm_port

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider

        # Adapters accept different construction kwargs (OpenAI: temperature
        # only; Anthropic: also max_tokens). Try the richer signature, fall
        # back to the minimal one.
        provider = AILlmProvider()
        try:
            self._llm = provider.get_default_port(temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS)
        except TypeError:
            self._llm = provider.get_default_port(temperature=_TEMPERATURE)
        return self._llm

    def propose(self, *, payload: dict, path: str, current_content: str) -> PatchProposal | None:
        """Return a grounded patch for ``path``, or ``None`` if unavailable.

        Never raises — a draft PR is an enhancement on top of a filed finding,
        never a gate on it.
        """
        if not path or current_content is None:
            return None
        if len(current_content) > _MAX_FILE_CHARS:
            logger.info("log_patch_advisor file_too_large path=%s chars=%s", path, len(current_content))
            return None

        prompt = (
            f"service: {payload.get('service') or 'unknown'}\n"
            f"level: {payload.get('level') or 'ERROR'}\n"
            f"error message: {(payload.get('message') or payload.get('signal') or '')[:1600]}\n"
            f"probable cause: {(payload.get('probable_cause') or '')[:600]}\n"
            f"suggested fix: {(payload.get('suggested_fix') or '')[:600]}\n"
            f"evidence:\n{self._evidence_text(payload)[:2000]}\n\n"
            f"file path: {path}\n"
            f"current file content:\n<<<FILE\n{current_content}\nFILE>>>\n\n"
            "Return the JSON now."
        )
        try:
            llm = self._get_llm()
            response = llm.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            logger.exception("log_patch_advisor llm call failed path=%s", path)
            return None

        proposal = self._parse(getattr(response, "content", "") or "", path)
        if proposal is None:
            return None
        if not self._is_grounded(payload, current_content, proposal.updated_content):
            logger.info("log_patch_advisor ungrounded patch rejected path=%s", path)
            return None
        return proposal

    @staticmethod
    def _evidence_text(payload: dict) -> str:
        lines = []
        for ev in payload.get("evidence") or []:
            if isinstance(ev, dict):
                lines.append(f"- {ev.get('type') or 'evidence'}: {ev.get('detail') or ''}")
        return "\n".join(lines)

    @staticmethod
    def _parse(content: str, expected_path: str) -> PatchProposal | None:
        text = content.strip()
        # Tolerate a model that wraps JSON in a code fence despite instructions.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.warning("log_patch_advisor unparseable output path=%s", expected_path)
            return None
        updated = data.get("updated_content")
        if not isinstance(updated, str) or not updated.strip():
            return None
        summary = str(data.get("change_summary") or "").strip()
        # The model edits the file it was given — the path is ours, not its.
        return PatchProposal(path=expected_path, updated_content=updated, change_summary=summary)

    @staticmethod
    def _is_grounded(payload: dict, old_content: str, new_content: str) -> bool:
        """The diff must touch a line carrying one of the finding's salient tokens.

        Deterministic, zero LLM. An identical file, or a change that only
        touches lines unrelated to the error's identifiers, is ungrounded.
        """
        if new_content == old_content:
            return False
        ground = [str(payload.get("message") or ""), str(payload.get("signal") or "")]
        for ev in payload.get("evidence") or []:
            if isinstance(ev, dict):
                ground.append(str(ev.get("detail") or ""))
        ground.append(str(payload.get("suggested_fix") or ""))
        tokens = {t.lower() for t in salient_tokens("\n".join(ground))}
        if not tokens:
            # No checkable identifiers at all → we cannot verify the patch
            # engages with the evidence; for code we ship to a PR, refuse.
            return False
        changed_lines = [
            line[1:].lower()
            for line in difflib.unified_diff(old_content.splitlines(), new_content.splitlines(), lineterm="")
            if line[:1] in ("+", "-") and not line.startswith(("+++", "---"))
        ]
        return any(tok in line for line in changed_lines for tok in tokens)
