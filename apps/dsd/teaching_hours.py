"""Domain rule: teaching hours of each teacher in a semester.

Implements: docs/especificacao/05_dsd_regras.md – the load of a teacher adds the weekly hours of
every class type assigned, weighted by the teacher's share (``h x s / 100``); a merged class is
one class and counts once; every group counts once, so N groups count N times; D12, D19, D60,
D70. Pure Python: no Django, no database.

The unit of calculation is the *teaching unit*: one class type of one offering, given to a
single audience (several merged turmas, or one group). A merge is therefore one unit and counts
once, and N groups are N units that count N times, each with its own teacher. There is no
"repetitions" counter on purpose: it would hide groups taught by different teachers.

The main figure is **weekly** hours, because the load range is measured in weekly hours summed
over the two semesters (D12). The semester hours (weekly x weeks of the semester, D60) are only
for display and for checking against ``Subject.semester_hours``.

All values are ``Decimal`` and nothing is rounded here. With two-decimal hours and two-decimal
percentages ``h x s / 100`` has at most six decimals, which the default decimal context holds
exactly, so sums stay exact and the shares of a unit that add up to 100 distribute exactly the
unit's hours. Rounding, if any, belongs to the display layer (D70).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def _decimal(value: object, name: str) -> Decimal:
    """Return ``value`` if it is a ``Decimal``, refusing floats, ints and ``None``.

    Raises:
        TypeError: if the value is not a ``Decimal``.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
    return value


@dataclass(frozen=True)
class AssignmentFact:
    """A teacher's share of one teaching unit.

    Attributes:
        teacher_id: id of the teacher.
        share: percentage of the unit given to the teacher, above 0 and at most 100; 100 when
            the teacher is alone, which is the normal case (D19).
    """

    teacher_id: int
    share: Decimal = HUNDRED

    def __post_init__(self) -> None:
        """Validate the share.

        Raises:
            TypeError: if ``share`` is not a ``Decimal``.
            ValueError: if ``share`` is not above 0 and at most 100.
        """
        share = _decimal(self.share, "share")
        if not ZERO < share <= HUNDRED:
            raise ValueError(f"share must be above 0 and at most 100, got {share}")


@dataclass(frozen=True)
class TeachingUnitFact:
    """One class type of one offering for one audience, with who teaches it.

    Attributes:
        id: identifier of the unit, unique in a calculation.
        offering_id: the offering (subject in the semester) the unit belongs to.
        class_type: code of the class type (T, TP, P, L, ...).
        weekly_hours: weekly hours of the class type in the study plan, above 0.
        class_group_ids: the turmas that attend together. Descriptive only: a merge of any
            number of turmas is still one class and counts once.
        subgroup_id: the group, when the audience is a group of a turma; ``None`` otherwise.
        assignments: the teachers and their shares; empty while nobody is assigned.
    """

    id: int
    offering_id: int
    class_type: str
    weekly_hours: Decimal
    class_group_ids: frozenset[int]
    subgroup_id: int | None = None
    assignments: tuple[AssignmentFact, ...] = field(default=())

    def __post_init__(self) -> None:
        """Validate the unit.

        Raises:
            TypeError: if ``weekly_hours`` is not a ``Decimal``.
            ValueError: if the hours are not above 0, the audience is empty, the class type is
                empty, or a teacher appears twice (one teacher per unit, shares are for
                sharing, D19).
        """
        if _decimal(self.weekly_hours, "weekly_hours") <= ZERO:
            raise ValueError(f"weekly_hours must be above 0, got {self.weekly_hours}")
        if not self.class_group_ids:
            raise ValueError("class_group_ids must name at least one turma")
        if not self.class_type:
            raise ValueError("class_type must not be empty")
        teachers = [a.teacher_id for a in self.assignments]
        if len(teachers) != len(set(teachers)):
            raise ValueError(f"unit {self.id}: a teacher appears twice; use the share (D19)")


@dataclass(frozen=True)
class TeachingLine:
    """The contribution of one unit to one teacher, so every number can be explained.

    Attributes:
        unit_id: the unit.
        offering_id: its offering.
        class_type: its class type code.
        unit_weekly_hours: weekly hours of the whole unit.
        share: the teacher's percentage of it.
        weekly_hours: ``unit_weekly_hours x share / 100``.
        semester_hours: ``weekly_hours x semester weeks``.
    """

    unit_id: int
    offering_id: int
    class_type: str
    unit_weekly_hours: Decimal
    share: Decimal
    weekly_hours: Decimal
    semester_hours: Decimal


@dataclass(frozen=True)
class TeacherTeachingHours:
    """Teaching hours of one teacher in the semester.

    Attributes:
        teacher_id: the teacher.
        weekly_hours: the sum of the weekly hours of every line (the figure compared with the
            load range, D12).
        semester_hours: ``weekly_hours x semester weeks``.
        weekly_by_class_type: weekly hours per class type code, sorted by code; the input of
            the preparation hours.
        lines: one line per unit, sorted by offering, class type and unit.
    """

    teacher_id: int
    weekly_hours: Decimal
    semester_hours: Decimal
    weekly_by_class_type: tuple[tuple[str, Decimal], ...]
    lines: tuple[TeachingLine, ...]


@dataclass(frozen=True)
class UnitTotals:
    """What a unit distributes among teachers, for the alerts about unassigned classes.

    Attributes:
        unit_id: the unit.
        weekly_hours: weekly hours of the unit.
        share_total: the sum of the shares assigned; 100 when the unit is fully assigned, 0
            when nobody teaches it.
        distributed_weekly_hours: ``weekly_hours x share_total / 100``.
    """

    unit_id: int
    weekly_hours: Decimal
    share_total: Decimal
    distributed_weekly_hours: Decimal


@dataclass(frozen=True)
class SemesterTeachingHours:
    """Result of the calculation for one semester.

    Attributes:
        semester_weeks: the weeks used for the semester hours (D60).
        teachers: teachers with at least one line, sorted by id.
        units: totals of every unit, sorted by id.
    """

    semester_weeks: Decimal
    teachers: tuple[TeacherTeachingHours, ...]
    units: tuple[UnitTotals, ...]

    def for_teacher(self, teacher_id: int) -> TeacherTeachingHours:
        """Return the hours of a teacher, or zeros when the teacher has no unit.

        Args:
            teacher_id: the teacher.

        Returns:
            The teacher's record; an all-zero record for a teacher with no assignments, whose
            load range still applies later.
        """
        for teacher in self.teachers:
            if teacher.teacher_id == teacher_id:
                return teacher
        return TeacherTeachingHours(teacher_id, ZERO, ZERO, (), ())


def share_hours(weekly_hours: Decimal, share: Decimal) -> Decimal:
    """Return the weekly hours that fall to a teacher: ``weekly_hours x share / 100``.

    Args:
        weekly_hours: weekly hours of the whole unit.
        share: the teacher's percentage of the unit.

    Returns:
        The exact product, with no rounding.

    Raises:
        TypeError: if either argument is not a ``Decimal``.
    """
    return _decimal(weekly_hours, "weekly_hours") * _decimal(share, "share") / HUNDRED


def semester_teaching_hours(
    units: Iterable[TeachingUnitFact], semester_weeks: Decimal
) -> SemesterTeachingHours:
    """Compute the teaching hours of every teacher in one semester.

    A teacher's weekly hours are the sum, over the units they teach, of the unit's weekly hours
    times their share. A unit with no teacher, or whose shares do not add up to 100, is
    calculated all the same and reported in ``units`` so that the alerts can flag it (05).
    Call it once per semester; the annual figure adds the two weekly totals (D12).

    Args:
        units: the teaching units of one semester of one DSD.
        semester_weeks: weeks of the semester (parameter, D60), above 0.

    Returns:
        The hours per teacher, with the lines that explain them, and the totals per unit.

    Raises:
        TypeError: if ``semester_weeks`` is not a ``Decimal``.
        ValueError: if ``semester_weeks`` is not above 0 or two units share an id.
    """
    if _decimal(semester_weeks, "semester_weeks") <= ZERO:
        raise ValueError(f"semester_weeks must be above 0, got {semester_weeks}")
    ordered = sorted(units, key=lambda u: u.id)
    ids = [u.id for u in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate unit id")

    lines_by_teacher: dict[int, list[TeachingLine]] = {}
    totals: list[UnitTotals] = []
    for fact in ordered:
        share_total = ZERO
        for assignment in fact.assignments:
            weekly = share_hours(fact.weekly_hours, assignment.share)
            share_total += assignment.share
            lines_by_teacher.setdefault(assignment.teacher_id, []).append(
                TeachingLine(
                    unit_id=fact.id,
                    offering_id=fact.offering_id,
                    class_type=fact.class_type,
                    unit_weekly_hours=fact.weekly_hours,
                    share=assignment.share,
                    weekly_hours=weekly,
                    semester_hours=weekly * semester_weeks,
                )
            )
        totals.append(
            UnitTotals(
                unit_id=fact.id,
                weekly_hours=fact.weekly_hours,
                share_total=share_total,
                distributed_weekly_hours=share_hours(fact.weekly_hours, share_total),
            )
        )

    teachers = []
    for teacher_id in sorted(lines_by_teacher):
        lines = sorted(
            lines_by_teacher[teacher_id], key=lambda x: (x.offering_id, x.class_type, x.unit_id)
        )
        by_type: dict[str, Decimal] = {}
        for line in lines:
            by_type[line.class_type] = by_type.get(line.class_type, ZERO) + line.weekly_hours
        weekly_total = sum((line.weekly_hours for line in lines), ZERO)
        teachers.append(
            TeacherTeachingHours(
                teacher_id=teacher_id,
                weekly_hours=weekly_total,
                semester_hours=weekly_total * semester_weeks,
                weekly_by_class_type=tuple(sorted(by_type.items())),
                lines=tuple(lines),
            )
        )
    return SemesterTeachingHours(semester_weeks, tuple(teachers), tuple(totals))
