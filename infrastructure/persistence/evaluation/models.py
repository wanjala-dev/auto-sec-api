"""Persistence for agent evaluation (ADR 0033).

Four tables, one spine:

    EvalSuite   ── a named set of cases for one agent type, owned by a workspace
      └─ EvalCase      ── one case, carrying what "right" meant for THIS case
    EvalRun     ── one execution of a suite, against one model, at one time
      └─ EvalCaseResult ── per-axis verdicts for one case in one run

Three things here are load-bearing and are not incidental schema choices.

**Every row is workspace-scoped.** The prompt-eval surface that preceded this
read reports off the filesystem, so every workspace saw the same 30 files baked
into the image. Evaluation results are a customer's own quality evidence; they
are tenant data, and on the pooled tier a missing ``workspace_id`` filter IS
the tenant boundary (see ``.claude/rules/django-conventions.md``).

**``EvalRun.model_slug`` is required.** ADR 0032 established that measurements
do not transfer between models — ``fix_confidence`` already returns *unproven*
with "measured on X, running Y". A suite result that does not record which
model produced it is a number with no meaning, and worse, a number that will be
compared against a later run of a different model.

**``EvalCaseResult.deep_run`` is the provenance link.** ADR 0033 D4: the "why
did it fail" drill-down is built on our own records, because ``DeepRunLog``
already persists system_prompt, user_prompt, llm_response, model_used and
tool_name per event. No vendor holds customer prompts for this.
"""

from __future__ import annotations

import uuid

from django.db import models


class EvalSuite(models.Model):
    """A named set of cases for one agent type, belonging to one workspace."""

    class Origin(models.TextChoices):
        MINED = "mined", "Mined from this workspace's history"
        CURATED = "curated", "Curated by Auto-Sec"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="eval_suites",
    )

    name = models.CharField(max_length=200)
    agent_type = models.CharField(max_length=100, db_index=True)
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.MINED)
    # The axis keys this suite grades, e.g. ["grounded", "fix_applies"].
    # Stored per suite rather than globally so adding an axis does not silently
    # rewrite the meaning of results already recorded under the old set.
    axes = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "evaluation_suite"
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("workspace", "name"), name="uniq_eval_suite_name_per_workspace")]
        indexes = [models.Index(fields=["workspace", "agent_type"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.agent_type})"


class EvalCase(models.Model):
    """One case: an input, where it came from, and what right looks like."""

    class SourceKind(models.TextChoices):
        SIGN_OFF = "sign_off", "Sign-off decision"
        FINDING = "finding", "Resolved finding"
        DEEP_RUN = "deep_run", "Deep run"
        CURATED = "curated", "Curated"

    class Label(models.TextChoices):
        GOOD = "good", "Known-good outcome"
        BAD = "bad", "Known-bad outcome"
        UNLABELLED = "unlabelled", "Unlabelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    suite = models.ForeignKey(EvalSuite, on_delete=models.CASCADE, related_name="cases")
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="eval_cases",
    )

    # Where this case came from, so a reviewer can go and look at the original.
    source_kind = models.CharField(max_length=20, choices=SourceKind.choices)
    source_ref = models.CharField(max_length=255, blank=True, default="")
    # The distinct scenario this case represents (ADR 0033 D3's diversity
    # stage). Two cases with the same scenario measure one thing twice.
    scenario = models.CharField(max_length=500, blank=True, default="")

    prompt_inputs = models.JSONField(default=dict, blank=True)
    # 1-4 concise criteria describing what "right" meant for THIS case — the
    # sign-off reviewer's actual objection, not a generic standard. These are
    # inputs to the axis judgement, never a separate score (ADR 0033 D10).
    solution_criteria = models.JSONField(default=list, blank=True)
    label = models.CharField(max_length=20, choices=Label.choices, default=Label.UNLABELLED)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluation_case"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("suite", "source_kind", "source_ref"),
                name="uniq_eval_case_source_per_suite",
            )
        ]
        indexes = [models.Index(fields=["workspace", "suite"])]

    def __str__(self) -> str:
        return f"{self.source_kind}:{self.source_ref or self.id}"


class EvalRun(models.Model):
    """One execution of a suite, against one model, at one time."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="eval_runs",
    )
    suite = models.ForeignKey(EvalSuite, on_delete=models.CASCADE, related_name="runs")

    agent_type = models.CharField(max_length=100)
    # REQUIRED, per ADR 0032: measurements do not transfer between models, so a
    # result without the model that produced it cannot be interpreted.
    model_slug = models.CharField(max_length=100)
    judge_model_slug = models.CharField(max_length=100, blank=True, default="")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    cases_total = models.PositiveIntegerField(default=0)
    cases_completed = models.PositiveIntegerField(default=0)

    # WHICH cases this run scored, frozen when the run was created (ADR 0033
    # D13). Two things depend on this and neither is bookkeeping.
    #
    # `dataset_hash` is a content fingerprint, so two runs can be compared only
    # when they asked the same questions. Without it, editing a case and
    # re-running looks exactly like the model changing — and the easiest way to
    # make a failing suite pass is to soften the criteria it is failing.
    #
    # `case_snapshot` is the id list, and it is what the runner iterates. A run
    # must NOT pick up cases added to its suite after it started: a suite that
    # grows mid-run would otherwise move its own denominator, and a "34 of 40"
    # would silently become "34 of 47" while nothing new was graded.
    dataset_hash = models.CharField(max_length=64, blank=True, default="")
    case_snapshot = models.JSONField(default=list, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    last_error = models.TextField(blank=True, default="")

    # Live progress reuses the existing BackgroundJob primitive rather than
    # inventing a second progress surface.
    background_job = models.ForeignKey(
        "core.BackgroundJob",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="eval_runs",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluation_run"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["workspace", "suite", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.suite_id} on {self.model_slug} [{self.status}]"


class EvalCaseResult(models.Model):
    """Per-axis verdicts for one case in one run, with its provenance link."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(EvalRun, on_delete=models.CASCADE, related_name="results")
    case = models.ForeignKey(EvalCase, on_delete=models.CASCADE, related_name="results")
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="eval_case_results",
    )

    # {"grounded": true, "fix_applies": false, ...} — binary per axis (D10).
    # A missing axis means NOT MEASURED for that axis, which is not the same as
    # a failure and must never be rendered as one.
    axis_verdicts = models.JSONField(default=dict, blank=True)
    # The judge's reasoning, emitted BEFORE its verdict (D6). Stored rather than
    # discarded because it is what a human needs when they open a failed case.
    judge_reasoning = models.TextField(blank=True, default="")
    judge_strengths = models.JSONField(default=list, blank=True)
    judge_weaknesses = models.JSONField(default=list, blank=True)
    # Second judge's verdicts, where a second model is available, for the
    # Cohen's-kappa agreement statistic in D6.
    second_judge_verdicts = models.JSONField(default=dict, blank=True)
    second_judge_model_slug = models.CharField(max_length=100, blank=True, default="")

    # Provenance: the run that produced the output being graded (D4).
    deep_run = models.ForeignKey(
        "ai.DeepRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="eval_case_results",
    )
    output = models.TextField(blank=True, default="")
    failure_reason = models.TextField(blank=True, default="")
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluation_case_result"
        ordering = ("created_at",)
        constraints = [models.UniqueConstraint(fields=("run", "case"), name="uniq_eval_result_per_run_case")]
        indexes = [models.Index(fields=["workspace", "run"])]

    def __str__(self) -> str:
        return f"{self.case_id} in {self.run_id}"
