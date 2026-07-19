from django import forms
from django.utils.translation import gettext_lazy as _


class HoneypotAuthenticationForm(forms.Form):
    """
    Simple form that mimics the admin login inputs; we never authenticate with it.
    """

    username = forms.CharField(
        label=_("Username"),
        max_length=150,
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput,
        strip=False,
    )
