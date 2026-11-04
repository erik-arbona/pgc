"""Tests for the phase-out of study plans and its effect on cross-course groups.

Implements: D48 – a new plan enters year by year, starting with the first curricular year;
the old plan keeps serving the higher years until it disappears. No database needed.
"""

from decimal import Decimal

from apps.academic.cross_course import SubjectFacts, check_group, effective_members
from apps.academic.plans import PlanFacts, plan_in_force

OLD = PlanFacts(id=1, start_year=2020)
NEW = PlanFacts(id=2, start_year=2027)
PLANS = [OLD, NEW]


def test_new_plan_serves_only_the_first_year_in_its_first_academic_year():
    """In 2027 the new plan covers year 1; years 2 to 4 still use the old plan."""
    assert plan_in_force(PLANS, curricular_year=1, academic_year=2027) == NEW.id
    for year in (2, 3, 4):
        assert plan_in_force(PLANS, curricular_year=year, academic_year=2027) == OLD.id


def test_new_plan_reaches_the_second_year_one_academic_year_later():
    """In 2028 the new plan covers years 1 and 2; years 3 and 4 use the old plan."""
    assert plan_in_force(PLANS, 2, 2028) == NEW.id
    assert plan_in_force(PLANS, 3, 2028) == OLD.id


def test_old_plan_disappears_when_the_new_plan_reaches_the_last_year():
    """The 4th year changes to the new plan in 2030 and not before."""
    assert plan_in_force(PLANS, 4, 2029) == OLD.id
    assert plan_in_force(PLANS, 4, 2030) == NEW.id


def test_a_plan_that_has_not_started_is_not_in_force():
    """Before 2027 the new plan serves nobody."""
    assert plan_in_force(PLANS, 1, 2026) == OLD.id


def test_no_plan_in_force_returns_none():
    """With only a plan that reaches year 2 later, year 2 has no plan yet."""
    assert plan_in_force([NEW], 2, 2027) is None


def test_the_latest_started_plan_wins_among_several():
    """With three plans, the most recent one that already reached the year applies."""
    third = PlanFacts(id=3, start_year=2029)
    assert plan_in_force([OLD, NEW, third], 1, 2029) == third.id
    assert plan_in_force([OLD, NEW, third], 2, 2029) == NEW.id


def subject(id, course_id, plan_id, curricular_year):
    """Build subject facts of a given plan and curricular year."""
    return SubjectFacts(
        id=id,
        course_id=course_id,
        plan_id=plan_id,
        name="Introdução à Programação",
        ects=Decimal("6"),
        semester=1,
        semester_hours=Decimal("75"),
        curricular_year=curricular_year,
    )


def test_old_plan_subject_leaves_the_group_when_the_new_plan_reaches_its_year():
    """A 2nd-year subject of the old plan counts in 2027 and stops counting in 2028."""
    old_second_year = subject(1, course_id=10, plan_id=OLD.id, curricular_year=2)
    other_course = subject(2, course_id=20, plan_id=50, curricular_year=2)
    plans = {10: PLANS, 20: [PlanFacts(id=50, start_year=2020)]}
    members = [old_second_year, other_course]
    assert effective_members(members, plans, 2027) == members
    assert effective_members(members, plans, 2028) == [other_course]


def test_a_group_whose_only_other_course_left_becomes_invalid_for_that_year():
    """With the old subject out, the group has a single course: the check reports it."""
    old_second_year = subject(1, course_id=10, plan_id=OLD.id, curricular_year=2)
    other_course = subject(2, course_id=20, plan_id=50, curricular_year=2)
    plans = {10: PLANS, 20: [PlanFacts(id=50, start_year=2020)]}
    members = effective_members([old_second_year, other_course], plans, 2028)
    assert check_group(members, allowed_course_ids={10, 20})


def test_new_plan_subjects_count_only_once_the_manager_adds_them_to_the_group():
    """Effective members come from the group's rows: nothing is added automatically."""
    new_first_year = subject(3, course_id=10, plan_id=NEW.id, curricular_year=1)
    plans = {10: PLANS}
    assert effective_members([], plans, 2027) == []
    assert effective_members([new_first_year], plans, 2027) == [new_first_year]
