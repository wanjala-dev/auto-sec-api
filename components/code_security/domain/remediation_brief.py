"""RemediationBrief — the structured artifact of an honest decline (task #145).

For ``guidance_only`` remediation classes the correct fix depends on knowledge
that lives in the customer's codebase (an issuer's key source, a serialisation
decision), so a generated patch is a guess wearing a fix's clothes — ADR 0025
records both Class B evidence fixtures fabricating concrete patches in all 10
passes. The honest outcome is an explicit DECLINE carrying this brief: what is
wrong, why a local edit cannot fix it, the design change as concrete steps, what
the customer must supply, and how they will know it is fixed.

The brief IS the artifact (Henry's standing rule: a finding in a connected repo
always carries an artifact — for a design change, the artifact is the brief,
never a bare NEEDS HUMAN chip). It rides the finding payload under
``shared_kernel.domain.triage.REMEDIATION_BRIEF_KEY``, renders on the board card
comment, and is surfaced to the HUD through the findings triage state.

Framework-free: no Django, no ORM — a domain value object.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemediationBrief:
    """What the operator reads instead of a fabricated patch."""

    #: What is wrong, named to THIS finding (the flagged file/rule).
    what_is_wrong: str
    #: Why a local edit cannot fix it — the reason a patch would be fabrication.
    why_not_patchable: str
    #: The design change, as concrete steps naming real components.
    design_change: tuple[str, ...]
    #: Evidence/keys/config only the customer can supply (may be empty).
    required_inputs: tuple[str, ...] = ()
    #: "How you'll know it's fixed" (may be empty, but the prompt asks for it).
    acceptance_criteria: tuple[str, ...] = ()

    @classmethod
    def from_raw(cls, raw: object) -> RemediationBrief | None:
        """Parse a model-returned (or payload-stored) brief; ``None`` when unusable.

        The floor for "usable" is the three load-bearing fields: what is wrong,
        why a local edit cannot fix it, and at least one concrete step. A brief
        missing any of them is not an artifact an operator can act on, and the
        caller must treat the response as a failed decline rather than stamping
        an empty brief onto the card.
        """
        if not isinstance(raw, dict):
            return None
        what = str(raw.get("what_is_wrong") or "").strip()
        why = str(raw.get("why_not_patchable") or "").strip()
        steps = _clean_list(raw.get("design_change"))
        if not what or not why or not steps:
            return None
        return cls(
            what_is_wrong=what,
            why_not_patchable=why,
            design_change=steps,
            required_inputs=_clean_list(raw.get("required_inputs")),
            acceptance_criteria=_clean_list(raw.get("acceptance_criteria")),
        )

    def as_dict(self) -> dict:
        return {
            "what_is_wrong": self.what_is_wrong,
            "why_not_patchable": self.why_not_patchable,
            "design_change": list(self.design_change),
            "required_inputs": list(self.required_inputs),
            "acceptance_criteria": list(self.acceptance_criteria),
        }

    def as_text(self) -> str:
        """The brief flattened to plain text — the grounding surface the
        deterministic verifier checks for the finding's anchors (rule / file /
        snippet identifiers)."""
        parts = [self.what_is_wrong, self.why_not_patchable]
        parts += list(self.design_change) + list(self.required_inputs) + list(self.acceptance_criteria)
        return "\n".join(p for p in parts if p)

    def render_markdown(self) -> str:
        """The card-comment rendering — markdown-clean (the HUD card callout
        renders comments), sections in reading order, no code fences (there is
        deliberately no code in a brief)."""
        lines = [
            "**What's wrong:** " + self.what_is_wrong,
            "",
            "**Why a local edit can't fix it:** " + self.why_not_patchable,
            "",
            "**The design change:**",
            *[f"{i}. {step}" for i, step in enumerate(self.design_change, start=1)],
        ]
        if self.required_inputs:
            lines += ["", "**What you need to supply:**", *[f"- {item}" for item in self.required_inputs]]
        if self.acceptance_criteria:
            lines += ["", "**How you'll know it's fixed:**", *[f"- {item}" for item in self.acceptance_criteria]]
        return "\n".join(lines)


def _clean_list(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    return tuple(s for s in (str(v or "").strip() for v in values) if s)
