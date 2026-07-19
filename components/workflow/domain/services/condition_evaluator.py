"""Condition evaluation — the predicate DSL behind autonomous branching.

A ``condition`` node carries a predicate; the engine evaluates it against the
run context (trigger payload + target + prior step outputs) and branches Yes/No
with no human in the loop. This module is the pure, framework-free evaluator —
the thing that lets a nonprofit build "if the donation was >= $500 -> major-donor
thank-you, else -> drip" without a person clicking a button.

Predicate shape (mirrors Keela's "match All / Any of these conditions")::

    {
        "match": "all",          # "all" (AND) | "any" (OR); default "all"
        "conditions": [
            {"field": "amount", "op": "gte", "value": 500},
            {"field": "contact.tags", "op": "not_contains", "value": "Staff"},
        ],
    }

A bare single condition ``{"field","op","value"}`` is also accepted. An empty or
missing predicate evaluates True (a pass-through condition is a no-op, not an
error) — only a structurally malformed predicate raises.

``field`` is a dotted path looked up in the context dict (``amount``,
``contact.donor_score``, ``trigger.campaign_id``, ``steps.<node>.satisfied``).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable

from components.workflow.domain.errors import WorkflowConditionError

_MISSING = object()


def evaluate_condition(predicate: Any, context: Dict[str, Any]) -> bool:
    """Evaluate ``predicate`` against ``context`` and return the branch outcome."""
    if not predicate:
        return True

    # Allow a bare single condition.
    if isinstance(predicate, dict) and "field" in predicate and "conditions" not in predicate:
        return _evaluate_one(predicate, context)

    if not isinstance(predicate, dict):
        raise WorkflowConditionError("Condition predicate must be an object.")

    conditions = predicate.get("conditions")
    if conditions is None:
        return True
    if not isinstance(conditions, list):
        raise WorkflowConditionError("Condition 'conditions' must be a list.")
    if not conditions:
        return True

    match = str(predicate.get("match", "all")).strip().lower()
    results = (_evaluate_one(cond, context) for cond in conditions)
    if match in ("any", "or"):
        return any(results)
    if match in ("all", "and"):
        return all(results)
    raise WorkflowConditionError(f"Unknown match mode {match!r}; expected 'all' or 'any'.")


def evaluate_switch(config: Any, context: Dict[str, Any]) -> "str | None":
    """Resolve a ``switch`` node to the label of the first matching case.

    A ``switch`` is the N-way generalisation of ``condition``: it carries an
    ordered list of cases, each with a ``label`` (matching an outgoing edge) and a
    ``predicate`` (same DSL as ``evaluate_condition``). The engine takes the edge
    labelled by the first case whose predicate is True; if none match it returns
    ``config["default_label"]`` (or ``None`` when no default is set, which the
    engine resolves to the first edge as a safety fallback).

    Shape::

        {
            "cases": [
                {"label": "major", "predicate": {"conditions": [{"field": "amount", "op": "gte", "value": 500}]}},
                {"label": "mid",   "predicate": {"conditions": [{"field": "amount", "op": "gte", "value": 100}]}},
            ],
            "default_label": "small",
        }
    """
    if not isinstance(config, dict):
        raise WorkflowConditionError("Switch config must be an object.")
    cases = config.get("cases")
    if cases is None:
        return config.get("default_label")
    if not isinstance(cases, list):
        raise WorkflowConditionError("Switch 'cases' must be a list.")
    for case in cases:
        if not isinstance(case, dict):
            raise WorkflowConditionError("Each switch case must be an object.")
        label = case.get("label")
        if not label:
            raise WorkflowConditionError("Each switch case requires a 'label'.")
        if evaluate_condition(case.get("predicate"), context):
            return str(label)
    return config.get("default_label")


def _evaluate_one(condition: Any, context: Dict[str, Any]) -> bool:
    if not isinstance(condition, dict):
        raise WorkflowConditionError("Each condition must be an object.")
    field = condition.get("field")
    op = str(condition.get("op", "eq")).strip().lower()
    expected = condition.get("value")
    if not field:
        raise WorkflowConditionError("Condition requires a 'field'.")

    actual = _resolve_path(context, str(field))
    return _apply_op(op, actual, expected)


def _resolve_path(context: Dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def _apply_op(op: str, actual: Any, expected: Any) -> bool:  # noqa: C901 - explicit dispatch
    present = actual is not _MISSING

    if op in ("is_set", "exists"):
        return present and actual not in (None, "", [], {})
    if op in ("is_empty", "not_set"):
        return (not present) or actual in (None, "", [], {})

    if not present:
        # Any comparison against a missing field is False (except the presence
        # ops handled above) — a condition can't match what isn't there.
        return False

    if op in ("eq", "equals", "=="):
        return _coerce_eq(actual, expected)
    if op in ("ne", "not_equals", "!="):
        return not _coerce_eq(actual, expected)
    if op in ("gt", ">"):
        return _num(actual) > _num(expected)
    if op in ("gte", ">="):
        return _num(actual) >= _num(expected)
    if op in ("lt", "<"):
        return _num(actual) < _num(expected)
    if op in ("lte", "<="):
        return _num(actual) <= _num(expected)
    if op == "between":
        low, high = _pair(expected)
        return _num(low) <= _num(actual) <= _num(high)
    if op in ("in", "any_of"):
        return any(_coerce_eq(actual, item) for item in _as_iterable(expected))
    if op in ("not_in", "none_of"):
        return not any(_coerce_eq(actual, item) for item in _as_iterable(expected))
    if op in ("contains", "contains_any"):
        return _contains(actual, expected)
    if op in ("not_contains", "excludes"):
        return not _contains(actual, expected)
    if op in ("starts_with",):
        return str(actual).lower().startswith(str(expected).lower())
    if op in ("ends_with",):
        return str(actual).lower().endswith(str(expected).lower())

    raise WorkflowConditionError(f"Unsupported condition op {op!r}.")


def _contains(actual: Any, expected: Any) -> bool:
    """True if ``actual`` (a list/set/string) contains any of ``expected``."""
    wanted = _as_iterable(expected)
    if isinstance(actual, (list, tuple, set)):
        haystack = {_norm(item) for item in actual}
        return any(_norm(w) in haystack for w in wanted)
    text = str(actual).lower()
    return any(str(w).lower() in text for w in wanted)


def _coerce_eq(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return bool(actual) == bool(expected)
    try:
        return _num(actual) == _num(expected)
    except WorkflowConditionError:
        return _norm(actual) == _norm(expected)


def _num(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise WorkflowConditionError(f"Value {value!r} is not numeric.")


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def _as_iterable(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return value
    return (value,)


def _pair(value: Any):
    items = list(_as_iterable(value))
    if len(items) != 2:
        raise WorkflowConditionError("'between' expects a [low, high] pair.")
    return items[0], items[1]
