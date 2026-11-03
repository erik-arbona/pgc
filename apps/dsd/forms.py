"""Forms of the DSD screens (T2.1).

Implements: docs/backlog_fase2.md T2.1 to T2.3.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academic.models import Coordination
from apps.core.generic import ReasonFieldsMixin, ReasonModelForm
from apps.rooms.models import RoomType
from apps.staff.models import Teacher

from .lifecycle_rules import ACTION_CLOSE, ACTION_OPEN, ACTION_REOPEN, ACTIONS, needs_reason
from .models import Dsd, Offering


def parse_seen(text: str) -> dict[int, int]:
    """Parse the ``unit id:version`` pairs a form carries for the optimistic lock (D54).

    Args:
        text: pairs separated by commas, for example ``"12:3,14:1"``.

    Returns:
        ``{unit id: version}``.

    Raises:
        forms.ValidationError: if the text is not made of such pairs.
    """
    try:
        return {
            int(unit): int(version)
            for unit, version in (pair.split(":") for pair in text.split(",") if pair)
        }
    except ValueError:
        raise forms.ValidationError(_("Dados do formulário inválidos.")) from None


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


class GenerateOfferingsForm(ReasonFieldsMixin, forms.Form):
    """Generate the offerings of one or both semesters, for one coordination or all (T2.3).

    ``coordination_ids`` limits the choice to the coordinations the manager covers (D69). The
    reason is optional: generating only creates records (D40).
    """

    SEMESTER_CHOICES = [("1", _("1.º semestre")), ("2", _("2.º semestre")), ("both", _("Ambos"))]

    semester = forms.ChoiceField(label=_("Semestre"), choices=SEMESTER_CHOICES, initial="both")
    coordination = forms.ModelChoiceField(
        label=_("Coordenação"),
        queryset=Coordination.objects.none(),
        required=False,
        empty_label=_("Todas as que posso gerir"),
    )
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, coordination_ids=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["coordination"].queryset = Coordination.objects.filter(pk__in=coordination_ids)
        self._setup_reason(required=False)


class LeadTeacherForm(ReasonFieldsMixin, forms.Form):
    """Choose the regente of an offering among the active teachers of its coordination (T2.3b).

    The form carries the version of the offering the user saw, for the optimistic lock (D54).
    The reason is required only when the offering already has a regente (D40).
    """

    teacher = forms.ModelChoiceField(
        label=_("Regente"),
        queryset=Teacher.objects.none(),
        required=False,
        empty_label=_("Sem regente"),
    )
    version = forms.IntegerField(widget=forms.HiddenInput)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, offering: Offering, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.offering = offering
        self.fields["teacher"].queryset = Teacher.objects.filter(
            coordination_id=offering.subject.coordination_id, is_active=True
        )
        self.fields["teacher"].initial = offering.lead_teacher_id
        self.fields["version"].initial = offering.version
        self._setup_reason(required=False)

    def clean(self):
        """Require the reason when the offering already has a regente."""
        self.reason_required = self.offering.lead_teacher_id is not None
        return super().clean()


class GroupCountForm(ReasonFieldsMixin, forms.Form):
    """Choose into how many groups a turma is divided for a class type (T3.2b, D90).

    ``seen`` carries the ``unit id:version`` pairs the user saw, for the optimistic lock (D54).
    The reason is required only when the turma is already divided (D40).
    """

    groups = forms.IntegerField(
        label=_("Número de grupos"),
        min_value=1,
        max_value=20,
        help_text=_("1 deixa a turma inteira; de 2 a 20 divide-a em grupos."),
    )
    seen = forms.CharField(required=False, widget=forms.HiddenInput)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, changing: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._changing = changing
        self._setup_reason(required=False)

    def clean_seen(self) -> dict[int, int]:
        """Parse ``seen`` into ``{unit id: version}``."""
        return parse_seen(self.cleaned_data.get("seen", ""))

    def clean(self):
        """Require the reason when the turma is already divided."""
        self.reason_required = self._changing
        return super().clean()


class MergeForm(ReasonFieldsMixin, forms.Form):
    """Ask for the room the merged unit needs and the reason (T3.3b, D91).

    The coordinator never chooses a room, only states the capacity (and optionally the type) of
    room needed (D64). ``seen`` carries the versions of the units, for the lock (D54).
    """

    room_capacity = forms.IntegerField(
        label=_("Lotação da sala pedida"),
        min_value=1,
        help_text=_("Lugares da sala de que a aula precisa; tem de comportar todos os alunos."),
    )
    room_type = forms.ModelChoiceField(
        label=_("Tipo de sala"),
        queryset=RoomType.objects.all(),
        required=False,
        empty_label=_("Qualquer tipo"),
    )
    host = forms.ChoiceField(
        label=_("Unidade que fica"),
        required=False,
        help_text=_("As horas contam pela disciplina desta unidade; por defeito, a primeira."),
    )
    seen = forms.CharField(required=False, widget=forms.HiddenInput)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, units=(), has_load_difference: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["host"].choices = [
            (
                unit.pk,
                f"{unit.offering.subject.code} – {unit.offering.subject.study_plan.course.name}",
            )
            for unit in units
        ]
        if has_load_difference:
            # Shown only when the subjects give a different weekly load (Q8, D92).
            self.fields["accept_load_difference"] = forms.BooleanField(
                label=_("Confirmo a junção apesar da carga semanal diferente"), required=False
            )
        self._setup_reason(required=False)

    def clean_seen(self) -> dict[int, int]:
        """Parse ``seen`` into ``{unit id: version}``."""
        return parse_seen(self.cleaned_data.get("seen", ""))


class SeparateForm(ReasonFieldsMixin, forms.Form):
    """Ask for the reason to take a member out of a merge (T3.3b, D40)."""

    seen = forms.IntegerField(required=False, widget=forms.HiddenInput)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup_reason(required=True)
