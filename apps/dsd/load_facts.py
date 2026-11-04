"""Adapter from the DSD models to the pure load rules: hours, preparation, annual load (T5.1b).

Implements: docs/backlog_fase2.md T5.1; D70 (a merge counts once, N groups count N times), D71
(preparation), D72-D74 (annual load, range and state), D92 (a cross-course merge counts the hours
of the host's subject), D94 (one teacher per unit, always at 100%).

Nothing is stored: everything is computed when asked, with a fixed number of queries whatever the
number of units. The rules live in ``teaching_hours``, ``preparation``, ``annual_load`` and
``load_status``, which know nothing about the models; this module only turns rows into their
input and their output into what the screens and the alerts need.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.academic.models import ClassType
from apps.core.parameters import SEMESTER_WEEKS, get_parameter
from apps.staff.models import Teacher
from apps.staff.services import load_ranges_for

from .annual_load import AnnualLoad, AnnualTeachingHours, annual_teaching_hours
from .load_status import LoadAssessment, LoadStatus, assess_load
from .models import Dsd, DsdSemester, OtherActivity, TeachingUnit
from .other_activities import ActivityFact, general_total, other_hours_by_teacher
from .preparation import preparation_by_teacher
from .teaching_hours import (
    AssignmentFact,
    TeachingUnitFact,
    round_hours,
    semester_teaching_hours,
)

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class TeacherLoad:
    """The load of one teacher in a DSD.

    Attributes:
        assessment: annual hours, range, state and extra hours (D72-D74).
        preparation: weekly preparation hours in the first and in the second semester (D71).
        other_hours: weekly hours of the other activities in each semester (T5.3, D95).
        general_total: teaching + preparation + other activities; only the teaching hours are
            compared with the range (D95).
    """

    assessment: LoadAssessment
    preparation: tuple[Decimal, Decimal]
    other_hours: tuple[Decimal, Decimal]
    general_total: Decimal


def unit_facts(
    dsd_semester: DsdSemester, *, teacher_ids: Iterable[int] | None = None
) -> tuple[list[TeachingUnitFact], list[int]]:
    """Turn the taught units of a semester into the facts the hours rule works with.

    The weekly hours of a unit are those of its class type in the load of the subject of the
    unit's own offering, which is the host's after a merge between courses (D92). A unit without
    such hours (its class type left the subject) cannot be a fact: it is returned apart, never
    dropped silently, so the alerts can name it.

    Args:
        dsd_semester: the semester of the DSD.
        teacher_ids: keep only the units taught by these teachers (any coordination).

    Returns:
        The facts, and the ids of the taught units that have no hours.
    """
    units = (
        TeachingUnit.objects.filter(offering__dsd_semester=dsd_semester, teacher__isnull=False)
        .select_related("class_type", "offering__subject")
        .prefetch_related(
            "offering__subject__class_loads",
            "members__class_group_link",
            "members__subgroup__class_group_link",
        )
        .order_by("pk")
    )
    if teacher_ids is not None:
        units = units.filter(teacher_id__in=list(teacher_ids))
    facts: list[TeachingUnitFact] = []
    without_hours: list[int] = []
    for unit in units:
        members = list(unit.members.all())
        groups = frozenset(member.turma_link.class_group_id for member in members)
        weekly = next(
            (
                load.weekly_hours
                for load in unit.offering.subject.class_loads.all()
                if load.class_type_id == unit.class_type_id
            ),
            None,
        )
        if weekly is None or weekly <= 0 or not groups:
            without_hours.append(unit.pk)
            continue
        facts.append(
            TeachingUnitFact(
                id=unit.pk,
                offering_id=unit.offering_id,
                class_type=unit.class_type.code,
                weekly_hours=weekly,
                class_group_ids=groups,
                subgroup_id=members[0].subgroup_id if len(members) == 1 else None,
                assignments=(AssignmentFact(teacher_id=unit.teacher_id),),
            )
        )
    return facts, without_hours


def teacher_loads(
    dsd: Dsd, teachers: Iterable[Teacher], as_of: date | None = None
) -> dict[int, TeacherLoad]:
    """Compute the load of some teachers in a DSD, as the rules define it (D70-D74).

    The units are those taught by the teachers in any coordination, so a teacher who changed
    coordination still counts all their units. A teacher with no unit has zero hours and is
    compared with the minimum of their range all the same. The range is the one in force on
    ``as_of`` (today by default; the date for a DSD closed in one semester only is Q11, open).

    Args:
        dsd: the DSD.
        teachers: saved teachers.
        as_of: the date the range must be valid on; today by default.

    Returns:
        A dictionary from teacher id to their load.

    Raises:
        LookupError: if the semester weeks parameter does not exist.
        ValueError: if a class type with hours has no preparation weight (never a silent zero).
    """
    people = list(teachers)
    ids = {teacher.pk for teacher in people}
    as_of = as_of or timezone.localdate()
    weeks = get_parameter(SEMESTER_WEEKS)
    weights = dict(ClassType.objects.values_list("code", "preparation_weight"))
    results = []
    preparation = []
    for semester in dsd.semesters.order_by("number"):
        facts, _ = unit_facts(semester, teacher_ids=ids)
        result = semester_teaching_hours(facts, weeks)
        results.append(result)
        preparation.append(preparation_by_teacher(result, weights))
    annual = {hours.teacher_id: hours for hours in annual_teaching_hours(*results)}
    other = other_hours_by_teacher(
        ActivityFact(teacher_id, number, hours)
        for teacher_id, number, hours in OtherActivity.objects.filter(
            dsd_semester__dsd=dsd, teacher_id__in=ids
        ).values_list("teacher_id", "dsd_semester__number", "weekly_hours")
    )
    ranges = load_ranges_for(people, as_of)
    loads: dict[int, TeacherLoad] = {}
    for teacher in people:
        hours = annual.get(teacher.pk) or AnnualTeachingHours.zero(teacher.pk)
        assessment = assess_load(
            AnnualLoad(
                teacher_id=teacher.pk,
                semester_weekly_hours=hours.semester_weekly_hours,
                weekly_hours=hours.weekly_hours,
                range=ranges[teacher.pk],
                as_of=as_of,
            )
        )
        prep = (preparation[0].get(teacher.pk, ZERO), preparation[1].get(teacher.pk, ZERO))
        other_hours = other.get(teacher.pk, (ZERO, ZERO))
        loads[teacher.pk] = TeacherLoad(
            assessment=assessment,
            preparation=prep,
            other_hours=other_hours,
            general_total=general_total(assessment.weekly_hours, prep, other_hours),
        )
    return loads


def status_text(assessment: LoadAssessment) -> str:
    """Return the state of a load in Portuguese, with the extra hours when above the maximum.

    Args:
        assessment: the assessment of a teacher's annual load.

    Returns:
        A short text for the screens, for example ``acima do máximo (+2.00 h)``.
    """
    texts = {
        LoadStatus.BELOW_MINIMUM: _("abaixo do mínimo"),
        LoadStatus.IN_RANGE: _("no intervalo"),
        LoadStatus.AT_MAXIMUM: _("no máximo"),
        LoadStatus.ABOVE_MAXIMUM: _("acima do máximo"),
        LoadStatus.NO_RANGE: _("sem intervalo"),
    }
    text = str(texts[assessment.status])
    if assessment.status == LoadStatus.ABOVE_MAXIMUM:
        text += f" (+{assessment.extra_hours} h)"
    return text


def assessment_with_unit(
    load: TeacherLoad, semester_number: int, weekly_hours: Decimal
) -> LoadAssessment:
    """Return the assessment a teacher would have if one more unit were given to them (T5.1b).

    The hours are added to the semester of the unit and the state is judged again against the same
    range; nothing is stored. Used to help choose a teacher before assigning.

    Args:
        load: the teacher's current load.
        semester_number: 1 or 2, the semester of the unit.
        weekly_hours: the weekly hours of the unit (a teacher alone gets all of them, D94).

    Returns:
        The assessment with the unit included.
    """
    first, second = load.assessment.semester_weekly_hours
    if semester_number == 1:
        first = round_hours(first + weekly_hours)
    else:
        second = round_hours(second + weekly_hours)
    return assess_load(
        AnnualLoad(
            teacher_id=load.assessment.teacher_id,
            semester_weekly_hours=(first, second),
            weekly_hours=first + second,
            range=load.assessment.range,
            as_of=load.assessment.as_of,
        )
    )
