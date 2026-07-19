"""Composition root for the feedback→eval bridge (SEE-190).

Wires ``RecordSignOffFeedbackUseCase`` to the Django eval-example repository and
to a capture callable that reaches the artifact's registered sign-off adapter to
snapshot its generated output. The cross-context call is APPLICATION-layer only
(``sign_off``'s registry provider + its port) — allowed; no foreign
infrastructure is imported.
"""

from __future__ import annotations

from components.agents.application.use_cases.record_sign_off_feedback_use_case import (
    RecordSignOffFeedbackUseCase,
)


def _capture_from_registry(artifact_type: str, artifact_id: str) -> dict | None:
    """Snapshot the artifact's generated output via its sign-off adapter.

    Returns ``None`` when the artifact type isn't registered (nothing to
    capture) or the adapter carries no capturable AI output (its default).
    """
    from components.sign_off.application.providers.sign_off_registry_provider import (
        get_sign_off_registry,
    )
    from components.sign_off.domain.errors import UnregisteredArtifactError

    try:
        adapter = get_sign_off_registry().get_adapter(artifact_type)
    except UnregisteredArtifactError:
        return None
    return adapter.capture_for_eval(artifact_id)


def build_record_sign_off_feedback_use_case() -> RecordSignOffFeedbackUseCase:
    from components.agents.infrastructure.repositories.django_eval_example_repository import (
        DjangoEvalExampleRepository,
    )

    return RecordSignOffFeedbackUseCase(
        store=DjangoEvalExampleRepository(),
        capture=_capture_from_registry,
    )


def build_get_few_shot_negatives_use_case():
    """Wire ``GetFewShotNegativesUseCase`` to the Django eval-example repo.

    The payoff half of the feedback loop (SEE-191): the writing tools call this
    to fetch the reviewer counter-examples they inject into the generation
    prompt. Lazy-imported so the pure application layer doesn't pull the ORM at
    module import time.
    """
    from components.agents.application.use_cases.get_few_shot_negatives_use_case import (
        GetFewShotNegativesUseCase,
    )
    from components.agents.infrastructure.repositories.django_eval_example_repository import (
        DjangoEvalExampleRepository,
    )

    return GetFewShotNegativesUseCase(store=DjangoEvalExampleRepository())
