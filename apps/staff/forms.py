"""Forms of ``staff`` for the PGC manager area.

Implements: docs/especificacao/02_perfis_e_dados.md – categories and positions entered by the
PGC manager. Every form that edits an existing record asks for a reason (D40).
"""

from django import forms
from django.forms.models import construct_instance
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.generic import ReasonModelForm, ScopedModelForm

from .models import Category, LoadRange, Position, Teacher


class CategoryForm(ReasonModelForm):
    """Create or edit a teacher category. Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = Category
        fields = ["code", "name", "position", "is_active"]


class PositionForm(ReasonModelForm):
    """Create or edit a position (cargo). Unchecking ``is_active`` deactivates it."""

    class Meta:
        model = Position
        fields = ["name", "position", "is_active"]


class TeacherForm(ScopedModelForm):
    """Create or edit a teacher; the coordinations offered are in the manager's Faculties (D51).

    Inactive categories are not offered, except the one the teacher already has. The
    ``positions`` field lists the active positions plus the ones the teacher already holds;
    only full-time teachers can hold positions (D56).
    """

    positions = forms.ModelMultipleChoiceField(
        queryset=Position.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Cargos"),
        help_text=_("Só para docentes a tempo inteiro."),
    )

    scope_field = "coordination"
    scope_filter = "faculty_id__in"

    class Meta:
        model = Teacher
        fields = ["identifier", "name", "coordination", "category", "teacher_type", "is_active"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        keep = [self.instance.category_id] if self.instance.pk else []
        categories = self.fields["category"].queryset
        self.fields["category"].queryset = categories.filter(is_active=True) | categories.filter(
            pk__in=keep
        )
        held = []
        if self.instance.pk:
            held = list(self.instance.position_assignments.values_list("position_id", flat=True))
            self.fields["positions"].initial = held
        self.fields["positions"].queryset = Position.objects.filter(
            is_active=True
        ) | Position.objects.filter(pk__in=held)
        self.fields["reason"] = self.fields.pop("reason")

    def clean(self):
        """Refuse positions on a teacher that is not full-time."""
        cleaned = super().clean()
        if cleaned.get("positions") and cleaned.get("teacher_type") != Teacher.Type.FULL_TIME:
            self.add_error("positions", _("Só os docentes a tempo inteiro têm cargos."))
        return cleaned


class LoadRangeForm(ReasonModelForm):
    """Create or edit an hours range (D58).

    The kind and the category, position or teacher type are fixed once the rule exists: to
    change them, delete the rule (while it has not started) and add another. Inactive categories
    and positions are not offered, except the one the rule already has. Consistency and overlap
    are checked by ``services.save_load_range``, which gives the messages in Portuguese.
    """

    class Meta:
        model = LoadRange
        fields = [
            "kind",
            "category",
            "position",
            "teacher_type",
            "minimum_hours",
            "maximum_hours",
            "valid_from",
        ]
        widgets = {"valid_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        keep_category = [self.instance.category_id] if self.instance.pk else []
        keep_position = [self.instance.position_id] if self.instance.pk else []
        categories, positions = self.fields["category"].queryset, self.fields["position"].queryset
        self.fields["category"].queryset = categories.filter(is_active=True) | categories.filter(
            pk__in=keep_category
        )
        self.fields["position"].queryset = positions.filter(is_active=True) | positions.filter(
            pk__in=keep_position
        )
        if self.instance.pk:
            for name in ("kind", "category", "position", "teacher_type"):
                self.fields[name].disabled = True
        else:
            self.initial.setdefault("valid_from", timezone.localdate())

    def _post_clean(self) -> None:
        """Build the instance from the form but skip the model's own validation.

        ``services.save_load_range`` checks the same rules (hours, overlap, subject) and gives
        the messages in Portuguese; the model's generic constraint messages would be English.
        """
        self.instance = construct_instance(
            self, self.instance, self._meta.fields, self._meta.exclude
        )
