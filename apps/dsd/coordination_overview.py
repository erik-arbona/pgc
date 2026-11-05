"""Data of the overview of a coordination: what needs attention and each teacher's load (T6.1).

Implements: docs/especificacao/07_arquitetura.md – overview of the coordination; D20, D98.

Adapter between the models and the pure rules in ``overview``: it reads the units of one
semester and the live load of the teachers (``load_facts``) and returns what the screen draws.
Nothing is stored. Tenders and deadlines are not here because they do not exist yet (D98).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.academic.models import Coordination
from apps.staff.models import Teacher

from .load_facts import TeacherLoad, load_text, teacher_loads
from .models import Dsd, DsdSemester, TeachingUnit
from .overview import AttentionItem, AttentionKind, LoadBar, TeacherFacts, attention_items, load_bar
from .services import stale_unit_ids


@dataclass(frozen=True)
class TeacherRow:
    """One teacher of the overview: the load, the bar and the state in words.

    Attributes:
        teacher: the teacher.
        load: the live load (annual hours, state, reason and extra hours).
        bar: the proportions of the bar.
        status: the state of the load in words, with the reason and extra hours (never colour
            alone, D98).
        css_class: the class that colours the bar for the state.
        foreign: the teacher belongs to another coordination and only appears because
            they teach a unit of this one; their load is the full annual one (D94).
    """

    teacher: Teacher
    load: TeacherLoad
    bar: LoadBar
    status: str
    css_class: str
    foreign: bool


@dataclass(frozen=True)
class CoordinationOverview:
    """What the overview of a coordination shows for one semester.

    Attributes:
        dsd: the DSD.
        semester: the semester of the DSD.
        coordination: the coordination.
        unassigned_units: current units of the coordination with no teacher.
        stale_units: obsolete units of the coordination.
        items: what needs attention, most urgent first.
        rows: one row per teacher, by name.
    """

    dsd: Dsd
    semester: DsdSemester
    coordination: Coordination
    unassigned_units: int
    stale_units: int
    items: list[AttentionItem]
    rows: list[TeacherRow]


def coordination_overview(
    dsd: Dsd, semester_number: int, coordination: Coordination
) -> CoordinationOverview:
    """Compute the overview of a coordination in one semester of a DSD (D20, D98).

    The teachers shown are the active ones of the coordination plus anyone who teaches one of its
    units, so a teacher who moved away still shows while they have lessons here. Their load is the
    annual one over the whole DSD; the units to assign and the obsolete ones are of the semester.

    Args:
        dsd: the DSD.
        semester_number: 1 or 2.
        coordination: the coordination.

    Returns:
        The overview.

    Raises:
        DsdSemester.DoesNotExist: if the DSD has no such semester.
    """
    semester = dsd.semesters.get(number=semester_number)
    units = list(
        TeachingUnit.objects.filter(
            offering__dsd_semester=semester, offering__subject__coordination=coordination
        ).values_list("pk", "teacher_id")
    )
    stale = stale_unit_ids(semester, coordination.pk)
    unassigned = sum(1 for pk, teacher_id in units if teacher_id is None and pk not in stale)
    teachers = list(
        Teacher.objects.filter(
            Q(coordination=coordination, is_active=True)
            | Q(pk__in={teacher_id for _unit, teacher_id in units if teacher_id is not None})
        )
        .select_related("category", "coordination")
        .order_by("name")
    )
    loads = teacher_loads(dsd, teachers)
    # What needs attention is what this coordinator can act on: a teacher of another
    # coordination is shown, marked, but their reason and extra hours are not ours (D69).
    facts = [
        TeacherFacts(
            teacher.pk,
            loads[teacher.pk].assessment.status,
            loads[teacher.pk].minimum_reason,
            loads[teacher.pk].extra.status,
        )
        for teacher in teachers
        if teacher.coordination_id == coordination.pk
    ]
    rows = []
    for teacher in teachers:
        load = loads[teacher.pk]
        resolved = load.assessment.range
        rows.append(
            TeacherRow(
                teacher=teacher,
                load=load,
                bar=load_bar(
                    load.assessment.weekly_hours,
                    resolved.minimum if resolved else None,
                    resolved.maximum if resolved else None,
                ),
                status=load_text(load),
                css_class=f"state-{load.assessment.status.value}",
                foreign=teacher.coordination_id != coordination.pk,
            )
        )
    return CoordinationOverview(
        dsd=dsd,
        semester=semester,
        coordination=coordination,
        unassigned_units=unassigned,
        stale_units=len(stale),
        items=attention_items(unassigned, len(stale), facts),
        rows=rows,
    )


def attention_text(item: AttentionItem) -> str:
    """Return the sentence of an attention item in Portuguese.

    Args:
        item: what needs attention.

    Returns:
        For example ``4 aulas por atribuir``.
    """
    texts = {
        AttentionKind.UNASSIGNED_UNITS: _("%(count)s aulas por atribuir"),
        AttentionKind.STALE_UNITS: _("%(count)s unidades obsoletas (o plano já não as pede)"),
        AttentionKind.REASON_MISSING: _("%(count)s docentes abaixo da mínima sem motivo"),
        AttentionKind.REASON_REFUSED: _("%(count)s motivos recusados pelo Conselho Executivo"),
        AttentionKind.REASON_PENDING: _("%(count)s motivos à espera do Conselho Executivo"),
        AttentionKind.EXTRA_PENDING: _("%(count)s docentes com horas extra por aceitar"),
        AttentionKind.NO_RANGE: _("%(count)s docentes sem intervalo de horas definido"),
    }
    return str(texts[item.kind]) % {"count": item.count}
