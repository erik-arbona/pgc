"""Tests for the reason of a load below the minimum and its review (T5.5).

Implements: docs/backlog_fase2.md T5.5; D16 (below the minimum the coordinator registers the
reason; the Executive Board can refuse it), D97, D86 (cell), D69 (scope), D54 (versions).
"""

# The ``world`` fixture comes from test_assignment; F811 flags every test that uses it.
# ruff: noqa: F811

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.academic.models import Coordination, Faculty
from apps.core.models import AuditEntry, Profile, ScopeKind
from apps.dsd.below_minimum import MinimumReasonState
from apps.dsd.load_facts import teacher_loads
from apps.dsd.models import BelowMinimumReason, BelowMinimumReview
from apps.dsd.services import (
    assign_teacher,
    change_state,
    review_minimum_reason,
    set_minimum_reason,
)
from apps.dsd.tests.test_assignment import unit_of, user_with, world  # noqa: F401
from apps.staff.models import Category, LoadRange

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def board(world, django_user_model):
    """A range 6-12 for the teachers and an Executive Board user of the Faculty."""
    LoadRange.objects.create(
        kind=LoadRange.Kind.CATEGORY,
        category=Category.objects.get(name="Doutor"),
        minimum_hours=D("6"),
        maximum_hours=D("12"),
        valid_from=date(2020, 1, 1),
    )
    world["ce"] = user_with(
        django_user_model,
        Profile.EXECUTIVE_BOARD,
        ScopeKind.FACULTY,
        world["coordination"].faculty_id,
        "ce",
    )
    # A board of another Faculty that really has a coordination: it covers something, just
    # not this teacher (a board that covers nothing would be refused by the first check).
    faculty_b = Faculty.objects.create(name="Faculdade B", code="FB")
    Coordination.objects.create(faculty=faculty_b, name="Coordenação da B")
    world["other_ce"] = user_with(
        django_user_model, Profile.EXECUTIVE_BOARD, ScopeKind.FACULTY, faculty_b.pk, "ce2"
    )
    return world


def open_cell(world):
    """Open the first semester for the coordination."""
    change_state(world["manager"], "open", [world["semester"]], [world["coordination"]])


def register(world, text="Docente em licença parcial", user=None, teacher=None, **kwargs):
    """Register the reason of a teacher below the minimum."""
    return set_minimum_reason(
        user or world["coordinator"],
        teacher or world["mine"],
        world["semester"].dsd,
        text,
        **kwargs,
    )


def review(world, record, decision="accepted", comment="", user=None, seen=None):
    """Review a reason as the Executive Board."""
    return review_minimum_reason(
        user or world["ce"],
        record,
        decision,
        comment,
        record.version if seen is None else seen,
    )


def state_of(world, teacher=None):
    """The state of the reason of a teacher in the live load."""
    teacher = teacher or world["mine"]
    return teacher_loads(world["semester"].dsd, [teacher])[teacher.pk].minimum_reason


def test_the_coordinator_registers_the_reason_of_a_teacher_below_the_minimum(board):
    """The reason is stored for the teacher and the year, and the state is pending."""
    open_cell(board)
    assert state_of(board) == MinimumReasonState.MISSING
    record = register(board)
    assert BelowMinimumReason.objects.get().text == "Docente em licença parcial"
    assert record.coordination == board["coordination"]
    assert state_of(board) == MinimumReasonState.PENDING


def test_registering_is_audited(board):
    """Who, what and when (rule 7)."""
    open_cell(board)
    register(board)
    assert AuditEntry.objects.get(entity="dsd.belowminimumreason").actor == board["coordinator"]


def test_a_teacher_who_is_not_below_the_minimum_takes_no_reason(board):
    """Above the minimum there is nothing to justify (D16)."""
    open_cell(board)
    for label, other in (("A", board["mine2"]), ("B", board["mine2"])):
        for class_type in ("T", "P"):
            assign_teacher(board["coordinator"], unit_of(board, label, class_type), other)
    assert state_of(board, board["mine2"]) == MinimumReasonState.NOT_NEEDED
    with pytest.raises(ValidationError):
        register(board, teacher=board["mine2"])
    assert BelowMinimumReason.objects.count() == 0


def test_the_text_is_required(board):
    """A blank reason is refused."""
    open_cell(board)
    with pytest.raises(ValidationError):
        register(board, "   ")


def test_changing_the_text_needs_the_version_and_keeps_one_record(board):
    """The second call updates the record; a missing or old version is stale."""
    open_cell(board)
    record = register(board)
    with pytest.raises(ValidationError):
        register(board, "Outro", seen_version=None)
    register(board, "Outro motivo", seen_version=record.version)
    with pytest.raises(ValidationError):
        register(board, "Terceiro", seen_version=record.version)
    assert BelowMinimumReason.objects.get().text == "Outro motivo"


def test_scope_and_profile_are_checked_when_registering(board):
    """Another coordination, a teacher account and the Executive Board cannot register."""
    open_cell(board)
    for user in (board["other_coordinator"], board["teacher_user"], board["ce"]):
        with pytest.raises(PermissionDenied):
            register(board, user=user)


def test_the_cell_state_rules_apply_to_the_coordinator(board):
    """Not opened: only the manager; closed: nobody (D86)."""
    with pytest.raises(ValidationError):
        register(board)
    register(board, user=board["manager"])


def test_the_board_accepts_a_reason(board):
    """Accepted: the state follows and the review is audited."""
    open_cell(board)
    record = register(board)
    review(board, record, "accepted")
    assert state_of(board) == MinimumReasonState.ACCEPTED
    assert BelowMinimumReview.objects.get().reviewed_by == board["ce"]
    assert AuditEntry.objects.filter(entity="dsd.belowminimumreview").exists()


def test_the_board_refuses_a_reason_with_a_comment(board):
    """Refused: the comment is required and the case goes back to the coordinator (Q14)."""
    open_cell(board)
    record = register(board)
    with pytest.raises(ValidationError):
        review(board, record, "refused", comment=" ")
    review(board, record, "refused", comment="Não justifica")
    assert state_of(board) == MinimumReasonState.REFUSED
    assert BelowMinimumReview.objects.get().comment == "Não justifica"


def test_changing_the_text_after_a_review_makes_it_pending_again(board):
    """The review was of the old text (D97)."""
    open_cell(board)
    record = register(board)
    review(board, record, "refused", comment="Não justifica")
    register(board, "Motivo melhor", seen_version=record.version)
    assert state_of(board) == MinimumReasonState.PENDING


def test_a_review_of_an_old_version_is_stale(board):
    """The Executive Board saw text that was changed meanwhile (D54)."""
    open_cell(board)
    record = register(board)
    register(board, "Outro motivo", seen_version=record.version)
    with pytest.raises(ValidationError):
        review(board, record, "accepted", seen=record.version)
    assert BelowMinimumReview.objects.count() == 0


def test_reviewing_again_replaces_the_decision(board):
    """One review per reason: the new decision replaces the old one, both audited."""
    open_cell(board)
    record = register(board)
    review(board, record, "refused", comment="Não")
    review(board, record, "accepted")
    assert BelowMinimumReview.objects.get().decision == "accepted"
    assert AuditEntry.objects.filter(entity="dsd.belowminimumreview").count() == 2


def test_only_the_board_of_the_faculty_reviews(board):
    """The coordinator, a teacher account and the board of another Faculty are refused."""
    open_cell(board)
    record = register(board)
    for user in (board["coordinator"], board["teacher_user"], board["other_ce"]):
        with pytest.raises(PermissionDenied):
            review(board, record, user=user)
    assert BelowMinimumReview.objects.count() == 0


def test_the_board_reviews_even_when_the_cell_is_closed(board):
    """Reviewing changes no DSD data, so a closed cell does not stop it (D97)."""
    open_cell(board)
    record = register(board)
    change_state(
        board["manager"], "close", [board["semester"]], [board["coordination"]], reason="fim"
    )
    review(board, record, "accepted")
    assert BelowMinimumReview.objects.count() == 1


def test_a_decision_other_than_accepted_or_refused_is_invalid(board):
    """Only the two decisions exist."""
    open_cell(board)
    record = register(board)
    with pytest.raises(ValidationError):
        review(board, record, "maybe")
