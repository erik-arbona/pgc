"""Forms of ``core`` for the PGC manager area.

Implements: D60. Only the value of a parameter is editable; editing asks for a reason (D40).
"""

from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .generic import ReasonModelForm
from .models import Parameter


class ParameterForm(ReasonModelForm):
    """Edit the value of a system parameter; it must be positive."""

    value = forms.DecimalField(
        label=_("Valor"), min_value=Decimal("0.01"), max_digits=8, decimal_places=2
    )

    class Meta:
        model = Parameter
        fields = ["value"]
