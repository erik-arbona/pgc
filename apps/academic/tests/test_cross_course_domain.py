"""Unit tests for the cross-course subject rules (no database needed).

Implements: docs/especificacao/04_modelo_de_dados.md – cross-course subjects: warnings when
semester or load differ. See D22 and D47.
"""

from decimal import Decimal

from apps.academic.cross_course import (
    SubjectFacts,
    WarningKind,
    check_group,
    compare_members,
)


def facts(id, course_id, plan_id=None, **overrides):
    """Build subject facts with sensible defaults."""
    data = dict(
        id=id,
        course_id=course_id,
        plan_id=plan_id if plan_id is not None else course_id,
        name="Introdução à Programação",
        ects=Decimal("6"),
        semester=1,
        semester_hours=Decimal("75"),
        weekly_hours={"T": Decimal("3"), "P": Decimal("2")},
    )
    data.update(overrides)
    return SubjectFacts(**data)


def kinds(warnings):
    """Return the set of warning kinds."""
    return {w.kind for w in warnings}


def test_identical_members_produce_no_warnings():
    """Same semester, hours and weekly split: nothing to warn about."""
    assert compare_members([facts(1, 10), facts(2, 20)]) == []


def test_different_semester_warns():
    """EIC in the 1st semester and TM in the 2nd cannot be merged: warn."""
    assert kinds(compare_members([facts(1, 10), facts(2, 20, semester=2)])) == {
        WarningKind.SEMESTER_DIFFERS
    }


def test_different_semester_hours_warn():
    """A different semester load is reported."""
    result = compare_members([facts(1, 10), facts(2, 20, semester_hours=Decimal("60"))])
    assert kinds(result) == {WarningKind.SEMESTER_HOURS_DIFFER}


def test_different_weekly_hours_of_one_class_type_warn_with_the_type():
    """The warning names the class type whose weekly hours differ."""
    other = facts(2, 20, weekly_hours={"T": Decimal("2"), "P": Decimal("2")})
    result = compare_members([facts(1, 10), other])
    assert kinds(result) == {WarningKind.CLASS_LOAD_DIFFERS}
    assert result[0].detail == "T"


def test_a_class_type_missing_on_one_side_warns():
    """A class type present in one member and absent in the other counts as a difference."""
    other = facts(2, 20, weekly_hours={"T": Decimal("3")})
    result = compare_members([facts(1, 10), other])
    assert kinds(result) == {WarningKind.CLASS_LOAD_DIFFERS}
    assert result[0].detail == "P"


def test_group_with_a_single_course_is_rejected():
    """A cross-course subject needs at least two different courses."""
    errors = check_group([facts(1, 10), facts(2, 10, plan_id=99)], allowed_course_ids={10})
    assert errors


def test_allowed_course_outside_the_members_is_rejected():
    """Merging is only allowed between courses that have a member subject."""
    errors = check_group([facts(1, 10), facts(2, 20)], allowed_course_ids={10, 20, 30})
    assert errors


def test_valid_group_has_no_errors_and_may_exclude_a_member_course():
    """A third course may be left out of the allowed set (declared in 2, refused in a 3rd)."""
    members = [facts(1, 10), facts(2, 20), facts(3, 30)]
    assert check_group(members, allowed_course_ids={10, 20}) == []
