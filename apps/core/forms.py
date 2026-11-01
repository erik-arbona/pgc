"""Forms of ``core`` for the PGC manager area.

Implements: D60. Only the value of a parameter is editable; editing asks for a reason (D40).
"""

from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .generic import ReasonFieldsMixin, ReasonModelForm
from .models import Parameter


class ParameterForm(ReasonModelForm):
    """Edit the value of a system parameter; it must be positive."""

    value = forms.DecimalField(
        label=_("Valor"), min_value=Decimal("0.01"), max_digits=8, decimal_places=2
    )

    class Meta:
        model = Parameter
        fields = ["value"]


class AccountCreateForm(ReasonFieldsMixin, forms.Form):
    """Create an account: username, names and e-mail. There is no password field (D62)."""

    username = forms.CharField(label=_("Nome de utilizador"), max_length=150)
    first_name = forms.CharField(label=_("Nome próprio"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Apelido"), max_length=150, required=False)
    email = forms.EmailField(label=_("Correio eletrónico"), required=False)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup_reason(required=False)


class AccountUpdateForm(ReasonFieldsMixin, forms.Form):
    """Edit the names and e-mail of an account; the username is not editable (D62)."""

    first_name = forms.CharField(label=_("Nome próprio"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Apelido"), max_length=150, required=False)
    email = forms.EmailField(label=_("Correio eletrónico"), required=False)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup_reason(required=True)
