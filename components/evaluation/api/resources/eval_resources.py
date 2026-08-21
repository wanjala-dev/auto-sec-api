"""Output DTOs for EVALUATE (ADR 0033, contract-frozen).

These exist so the wire shape has one owner. The frontend renders straight from
this payload, and the single most consequential field is ``pass_rate``: it is
``None`` below the measurement floor and must serialise as JSON ``null``, never
as ``0``. `null` and `0.0` mean opposite things — "not measured" and "everything
failed" — and this product has already shipped that confusion once (#415).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AxisResource:
    axis: str
    passed: int
    measured: int
    pass_rate: float | None
    tier: str
    tier_label: str
    may_conclude: bool

    @classmethod
    def from_evidence(cls, evidence) -> "AxisResource":
        data = evidence.as_dict()
        return cls(**data)

    def as_dict(self) -> dict:
        return {
            "axis": self.axis,
            "passed": self.passed,
            "measured": self.measured,
            "pass_rate": self.pass_rate,
            "tier": self.tier,
            "tier_label": self.tier_label,
            "may_conclude": self.may_conclude,
        }


@dataclass(frozen=True)
class CaseResultResource:
    id: str
    case_id: str
    scenario: str
    source_kind: str
    source_ref: str
    axis_verdicts: dict
    judge_reasoning: str
    judge_strengths: list = field(default_factory=list)
    judge_weaknesses: list = field(default_factory=list)
    failure_reason: str = ""
    deep_run_id: str | None = None
    agreement: dict | None = None

    @classmethod
    def from_row(cls, row) -> "CaseResultResource":
        return cls(
            id=str(row.id),
            case_id=str(row.case_id),
            scenario=row.case.scenario,
            source_kind=row.case.source_kind,
            source_ref=row.case.source_ref,
            # An axis absent from this dict is NOT MEASURED. The frontend
            # depends on absence, so it must not be filled in with False here.
            axis_verdicts=row.axis_verdicts or {},
            judge_reasoning=row.judge_reasoning,
            judge_strengths=row.judge_strengths or [],
            judge_weaknesses=row.judge_weaknesses or [],
            failure_reason=row.failure_reason,
            deep_run_id=str(row.deep_run_id) if row.deep_run_id else None,
            agreement=(
                {
                    "second_judge_model_slug": row.second_judge_model_slug,
                    "verdicts": row.second_judge_verdicts,
                }
                if row.second_judge_verdicts
                else None
            ),
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "scenario": self.scenario,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "axis_verdicts": self.axis_verdicts,
            "judge_reasoning": self.judge_reasoning,
            "judge_strengths": self.judge_strengths,
            "judge_weaknesses": self.judge_weaknesses,
            "failure_reason": self.failure_reason,
            "deep_run_id": self.deep_run_id,
            "agreement": self.agreement,
        }


@dataclass(frozen=True)
class RunResource:
    id: str
    suite_id: str
    suite_name: str
    model_slug: str
    status: str
    started_at: object
    finished_at: object
    cases_total: int
    cases_completed: int
    cost_usd: str

    @classmethod
    def from_row(cls, run) -> "RunResource":
        return cls(
            id=str(run.id),
            suite_id=str(run.suite_id),
            suite_name=run.suite.name,
            model_slug=run.model_slug,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            cases_total=run.cases_total,
            cases_completed=run.cases_completed,
            cost_usd=f"{run.cost_usd:.4f}",
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "model_slug": self.model_slug,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cases_total": self.cases_total,
            "cases_completed": self.cases_completed,
            "cost_usd": self.cost_usd,
        }
