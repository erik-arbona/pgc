"""The DSD scenario of the fictitious data: assignments in eight different situations (T8.1).

Implements: docs/dados_ficticios.md; docs/backlog_fase2.md T8.1; D65, D94-D101.

It builds, on top of the structure of ``loader``, the DSD of the demo year with its offerings, the
first semester open, estimated enrolments, and teacher assignments that put the eight demo
teachers in eight different situations of the live load, so that every state can be seen on the
screens: below the minimum with each state of the reason (missing, waiting for the board, refused,
accepted), in range, at the maximum, and above it with the extra hours accepted or not.

Every write goes through the services the screens use, so the same permissions and rules apply;
the actor is the ``demo_gestor`` account (the services need a user), and the reviews are made by
the demo Executive Board accounts. Each step runs only if its result is not there yet, and the
assignments only if nobody has been given a unit, so loading again never overrides what a person
has done.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.academic.models import ClassGroup, Coordination
from apps.academic.models import Enrollment as EnrollmentModel
from apps.dsd.models import (
    AcceptedExtraHours,
    BelowMinimumReason,
    CoordinationSemester,
    Dsd,
    Offering,
    OtherActivity,
    TeachingUnit,
)
from apps.dsd.services import (
    add_activity,
    assign_teacher,
    change_state,
    create_dsd,
    generate_offerings,
    review_minimum_reason,
    set_accepted_extra,
    set_minimum_reason,
)
from apps.staff.models import Teacher

# Students estimated for each turma (course code, label): small numbers, clearly test values.
ENROLMENT = {("A", "A"): 30, ("A", "B"): 25, ("B", ""): 28, ("C", ""): 22, ("M", ""): 12}

# teacher -> the lessons they give, as (subject code, class type, turma label). Weekly hours: A111
# is T3+P2 in each of the two turmas A and B; B111 and C111 are T3+P2; M111 is T2+TP2; the
# first-semester second subjects are T4; the second-semester ones are T4 (first subject) or T2+L2
# (second subject). Collaborators and competition teachers have a range of their own with no
# minimum (D46), so only the full-time teachers can be below it. The hours of each teacher are
# chosen against the test ranges of ``loader.RANGES`` so that each one lands in a different state.
ASSIGNMENTS: dict[str, list[tuple[str, str, str]]] = {
    # 5 h in a range of 6-16: below the minimum, reason refused by the board
    "DT001": [("B111", "T", ""), ("B111", "P", "")],
    # 12 h in a range of 2-8: above the maximum, extra hours accepted
    "DT002": [("B121", "T", ""), ("C121", "T", ""), ("M121", "T", "")],
    # 2 h in a range of 4-12: below the minimum, reason accepted by the board
    "DT003": [("B122", "T", "")],
    # 4 h in a range of 8-18: below the minimum, no reason given
    "DT004": [("C112", "T", "")],
    # 8 h in a range of 10-20: below the minimum, reason waiting for the board
    "DT005": [("M112", "T", ""), ("M122", "T", ""), ("M122", "L", "")],
    # 20 h, a collaborator with a maximum of 20 and no minimum: exactly at the maximum
    "DT006": [
        ("A111", "T", "A"),
        ("A111", "T", "B"),
        ("A111", "P", "A"),
        ("A111", "P", "B"),
        ("A121", "T", "A"),
        ("A121", "T", "B"),
        ("M111", "T", ""),
    ],
    # 22 h, a collaborator with a maximum of 20: above it, extra hours not accepted yet
    "DT007": [
        ("A112", "T", "A"),
        ("A112", "T", "B"),
        ("B112", "T", ""),
        ("A122", "T", "A"),
        ("A122", "L", "A"),
        ("A122", "T", "B"),
        ("A122", "L", "B"),
        ("B122", "L", ""),
    ],
    # 4 h, a competition teacher with a maximum of 18 and no minimum: in range
    "DT008": [("C122", "T", ""), ("C122", "L", "")],
}


def _unit(dsd: Dsd, code: str, class_type: str, label: str) -> TeachingUnit:
    """Return the unit of a subject, class type and turma of the demo DSD."""
    return TeachingUnit.objects.get(
        offering__dsd_semester__dsd=dsd,
        offering__subject__code=code,
        class_type__code=class_type,
        members__class_group_link__class_group__label=label,
    )


def load_dsd_scenario(loader, year, coordinations: dict[str, Coordination]) -> None:
    """Create the DSD of the demo year and the assignments, only what is missing.

    Args:
        loader: the ``DemoLoader`` (it counts what is created and creates enrolments).
        year: the demo academic year.
        coordinations: the demo coordinations by code (C1 to C4).
    """
    user_model = get_user_model()
    manager = user_model.objects.get(username="demo_gestor")
    dsd = Dsd.objects.filter(academic_year=year).first()
    if dsd is None:
        dsd = create_dsd(year, manager)
        loader._count("Dsd")
    _load_enrolments(loader, year)
    semesters = list(dsd.semesters.order_by("number"))
    if not Offering.objects.filter(dsd_semester__in=semesters).exists():
        result = generate_offerings(manager, semesters)
        for _ in range(getattr(result, "created", 0) or 0):
            loader._count("Offering")
    first = semesters[0]
    if not CoordinationSemester.objects.filter(dsd_semester=first).exists():
        change_state(manager, "open", [first], list(coordinations.values()))
        loader._count("CoordinationSemester")
    if TeachingUnit.objects.filter(teacher__isnull=False).exists():
        return  # somebody already gave lessons: do not override a person's work
    teachers = {t.identifier: t for t in Teacher.objects.filter(identifier__in=ASSIGNMENTS)}
    for identifier, lessons in ASSIGNMENTS.items():
        for code, class_type, label in lessons:
            assign_teacher(manager, _unit(dsd, code, class_type, label), teachers[identifier])
            loader._count("assignment")
    _load_reasons_and_extras(loader, dsd, manager, teachers, semesters)


def _load_enrolments(loader, year) -> None:
    """Estimate the students of each demo turma."""
    for group in ClassGroup.objects.select_related("course").order_by("pk"):
        code = group.course.name.rsplit(" ", 1)[-1]
        students = ENROLMENT.get((code, group.label))
        if students is None:
            continue
        loader._ensure(
            EnrollmentModel,
            {"class_group": group, "academic_year": year, "kind": EnrollmentModel.Kind.ESTIMATED},
            {"students": students},
        )


def _load_reasons_and_extras(loader, dsd, manager, teachers, semesters) -> None:
    """Give the reasons, their reviews, the accepted extra hours and two other activities."""
    board = get_user_model().objects.get(username="demo_ce")
    if not AcceptedExtraHours.objects.exists():
        # DT002 has 4 h above its maximum and accepted them; DT007 has 2 h and has not.
        set_accepted_extra(manager, teachers["DT002"], dsd, Decimal("4"))
        loader._count("AcceptedExtraHours")
    if not BelowMinimumReason.objects.exists():
        # DT004 gets no reason on purpose (missing) and DT005's is never reviewed (waiting).
        set_minimum_reason(manager, teachers["DT005"], dsd, "Docente de teste: baixa parcial.")
        refused = set_minimum_reason(
            manager, teachers["DT001"], dsd, "Docente de teste: motivo vago."
        )
        accepted = set_minimum_reason(manager, teachers["DT003"], dsd, "Docente de teste: licença.")
        loader._count("BelowMinimumReason")
        review_minimum_reason(
            board, refused, "refused", "Dado de teste: falta detalhar o motivo.", refused.version
        )
        review_minimum_reason(board, accepted, "accepted", "", accepted.version)
    if not OtherActivity.objects.exists():
        add_activity(
            manager,
            teachers["DT002"],
            semesters[0],
            OtherActivity.Kind.RESEARCH,
            "Projeto de investigação de teste",
            Decimal("3"),
        )
        add_activity(
            manager,
            teachers["DT006"],
            semesters[1],
            OtherActivity.Kind.MANAGEMENT,
            "Coordenação de teste",
            Decimal("2"),
        )
        loader._count("OtherActivity")
