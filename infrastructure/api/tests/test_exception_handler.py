"""Unit tests for the custom DRF exception handler."""

from __future__ import annotations

from rest_framework import status

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DomainError,
    IntegrationError,
    NotFoundError,
    ValidationError,
)
from infrastructure.api.exception_handler import custom_exception_handler


def _ctx():
    return {"view": None, "request": None}


class TestCustomExceptionHandler:
    def test_validation_error_returns_400(self):
        exc = ValidationError("Invalid input")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["error"] == "Invalid input"
        assert resp.data["error_code"] == "ValidationError"

    def test_not_found_error_returns_404(self):
        exc = NotFoundError("Resource not found")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_conflict_error_returns_409(self):
        exc = ConflictError("Duplicate detected")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_authorization_error_returns_403(self):
        exc = AuthorizationError("Not allowed")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_integration_error_returns_502(self):
        exc = IntegrationError("Stripe down", service="stripe")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY

    def test_configuration_error_returns_503(self):
        exc = ConfigurationError("Missing API key")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_generic_domain_error_returns_400(self):
        exc = DomainError("Something wrong")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_payment_specific_errors_map_correctly(self):
        from components.payments.domain.errors import (
            DisputeNotFoundError,
            PaymentMethodNotFoundError,
            PaymentValidationError,
            ProviderUnavailableError,
            RefundValidationError,
        )

        assert custom_exception_handler(PaymentMethodNotFoundError("no method"), _ctx()).status_code == 404
        assert custom_exception_handler(PaymentValidationError("bad data"), _ctx()).status_code == 400
        assert custom_exception_handler(RefundValidationError("too much"), _ctx()).status_code == 400
        assert custom_exception_handler(DisputeNotFoundError("no dispute"), _ctx()).status_code == 404
        assert custom_exception_handler(ProviderUnavailableError("stripe"), _ctx()).status_code == 502

    def test_unhandled_exception_returns_none(self):
        exc = RuntimeError("unexpected")
        resp = custom_exception_handler(exc, _ctx())
        assert resp is None

    def test_empty_message_uses_class_name(self):
        exc = ValidationError("")
        resp = custom_exception_handler(exc, _ctx())
        assert resp.data["error"] == "ValidationError"
