"""Contract test: the public payment-method serializer must expose the
connected account's settlement currency.

The public donate form (JoinPage / PublicRecipientSponsorForm) labels its
amount field with this so donors see the currency they'll actually be
charged in, instead of a hard-coded "USD". Removing the field silently
reverts the donate form to the wrong-currency label, so pin it here.
"""
from components.payments.mappers.rest.payment_serializers import (
    PublicPaymentMethodSerializer,
)


def test_public_payment_method_serializer_exposes_settlement_currency():
    fields = PublicPaymentMethodSerializer().fields
    assert "settlement_currency" in fields, (
        "PublicPaymentMethodSerializer must expose settlement_currency — the "
        "public donate form depends on it to label the amount field with the "
        "connected account's charge currency."
    )
