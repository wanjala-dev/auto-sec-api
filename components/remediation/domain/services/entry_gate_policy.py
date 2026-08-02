"""EntryGatePolicy — the pure decision function for the D1 entry-gate.

This is the security spine, expressed as a framework-free domain service so the
rule is unit-testable in isolation and lives in exactly one place. The
application use case gathers the three facts through read-ports, then calls this
to decide; the use case NEVER re-implements the rule inline. Keeping "all three
must hold" here (not scattered across a use case or a controller) is what makes
the gate auditable and impossible to weaken by accident.
"""

from __future__ import annotations

from components.remediation.domain.errors import EntryGateNotSatisfiedError
from components.remediation.domain.value_objects.gate_conditions import GateConditions


class EntryGatePolicy:
    """Decides whether a candidate may enter the retrievable corpus."""

    @staticmethod
    def is_admissible(conditions: GateConditions) -> bool:
        return conditions.satisfied

    @staticmethod
    def enforce(conditions: GateConditions) -> None:
        """Raise :class:`EntryGateNotSatisfiedError` unless all three conditions
        hold. The use case calls this before constructing any entity — a refusal
        here means no ``RemediationEntry`` is ever created."""
        if not conditions.satisfied:
            raise EntryGateNotSatisfiedError(conditions.unmet_reasons())
