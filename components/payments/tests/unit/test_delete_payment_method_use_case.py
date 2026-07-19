from __future__ import annotations

from uuid import uuid4

from components.payments.application.use_cases.delete_payment_method_use_case import (
    DeletePaymentMethodUseCase,
)
from components.payments.domain.errors import PaymentMethodNotFoundError


class FakePaymentMethodRepository:
    def __init__(self, deleted: bool):
        self.deleted = deleted
        self.deleted_method_id = None
        self.updated_by_id = None

    def soft_delete_method(self, *, method_id, updated_by_id=None):
        self.deleted_method_id = method_id
        self.updated_by_id = updated_by_id
        return self.deleted


def test_delete_payment_method_use_case_deletes_existing_method():
    repository = FakePaymentMethodRepository(deleted=True)
    use_case = DeletePaymentMethodUseCase(repository)
    method_id = uuid4()
    user_id = uuid4()

    use_case.execute(method_id=method_id, updated_by_id=user_id)

    assert repository.deleted_method_id == method_id
    assert repository.updated_by_id == user_id


def test_delete_payment_method_use_case_raises_for_missing_method():
    repository = FakePaymentMethodRepository(deleted=False)
    use_case = DeletePaymentMethodUseCase(repository)

    try:
        use_case.execute(method_id=uuid4())
    except PaymentMethodNotFoundError as exc:
        assert "was not found" in str(exc)
    else:  # pragma: no cover - assertion fallback
        raise AssertionError("Expected PaymentMethodNotFoundError")
