"""Forms of the DSD screens (T2.1).

Implements: docs/backlog_fase2.md T2.1 and T2.2.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academic.models import Coordination
from apps.core.generic import ReasonFieldsMixin, ReasonModelForm

from .lifecycle_rules import ACTION_CLOSE, ACTION_OPEN, ACTION_REOPEN, ACTIONS, needs_reason
from .models import Dsd


class DsdForm(ReasonModelForm):
    """Choose the academic year of the new DSD.

    The uniqueness is not validated here: ``create_dsd`` refuses a second DSD with a clear
    message, also when two managers create it at the same time (D43).
    """

    class Meta:
        model = Dsd
        fields = ["academic_year"]

    def validate_unique(self) -> None:
        """Skip Django's generic unique message; the service gives the clear one."""


class StateChangeForm(ReasonFieldsMixin, forms.Form):
    """Open, close or reopen a semester for one coordination or for all (T2.2, D86).

    The reason is optional to open and required to close or reopen (D40).
    """

    ACTION_CHOICES = [
        (ACTION_OPEN, _("Abrir")),
        (ACTION_CLOSE, _("Fechar")),
        (ACTION_REOPEN, _("Reabrir")),
    ]
    SEMESTER_CHOICES = [("1", _("1.º semestre")), ("2", _("2.º semestre")), ("both", _("Ambos"))]

    action = forms.ChoiceField(label=_("Ação"), choices=ACTION_CHOICES)
    semester = forms.ChoiceField(label=_("Semestre"), choices=SEMESTER_CHOICES)
    coordination = forms.ModelChoiceField(
        label=_("Coordenação"),
        queryset=Coordination.objects.all(),
        required=False,
        empty_label=_("Todas as coordenações"),
    )
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup_reason(required=False)

    def clean(self):
        """Require the reason for the actions that change an existing state."""
        action = self.data.get(self.add_prefix("action"))
        self.reason_required = action in ACTIONS and needs_reason(action)
        return super().clean()
