"""Domain rule: the annual range of lesson hours of a teacher.

Implements: docs/especificacao/05_dsd_regras.md – range of lesson hours; D11 (the range with
the lowest maximum wins), D12 (hours are weekly hours summed over both semesters), D46 (a
range per teacher type), D56, D58. Pure Python: no Django, no views, no database.

The ranges are parameters entered by the PGC manager, never constants in the code (CLAUDE.md
rule 6). Each rule has a validity start date; the rule in force for a subject on a date is the
one with the latest ``valid_from`` on or before that date, so a change applies from its date and
a closed DSD can always be recomputed with the values of its time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

# Teacher types. Same values as ``staff.models.Teacher.Type``; repeated here so that this module
# does not depend on Django.
FULL_TIME = "full_time"
HABITUAL_COLLABORATOR = "habitual_collaborator"
COMPETITION = "competition"


class RuleKind(StrEnum):
    """What a rule refers to."""

    CATEGORY = "category"
    POSITION = "position"
    TEACHER_TYPE = "teacher_type"


# Order used to break a tie that no other criterion decides: position, then category, then type.
_KIND_ORDER = {RuleKind.POSITION: 0, RuleKind.CATEGORY: 1, RuleKind.TEACHER_TYPE: 2}

Subject = tuple[RuleKind, "int | str"]


@dataclass(frozen=True)
class RangeRule:
    """A range of lesson hours with its validity start.

    Attributes:
        id: identifier of the rule.
        kind: what ``ref`` refers to.
        ref: category id, position id or teacher type value, according to ``kind``.
        minimum: minimum hours; ``None`` when there is no minimum (D46).
        maximum: maximum hours.
        valid_from: first day on which the rule applies (inclusive).
    """

    id: int
    kind: RuleKind
    ref: int | str
    minimum: Decimal | None
    maximum: Decimal
    valid_from: date


@dataclass(frozen=True)
class TeacherFacts:
    """What the rule needs to know about a teacher.

    Attributes:
        teacher_type: one of ``FULL_TIME``, ``HABITUAL_COLLABORATOR`` and ``COMPETITION``.
        category_id: id of the teacher's category.
        position_ids: ids of the positions held; only full-time teachers have any (D56).
    """

    teacher_type: str
    category_id: int
    position_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ResolvedRange:
    """The range that applies to a teacher on a date.

    Attributes:
        minimum: minimum hours of the winning rule; ``None`` if it has none.
        maximum: maximum hours of the winning rule.
        rule_id: id of the winning rule.
        tied_rule_ids: ids of other rules in force with the same maximum, in id order.
        missing: subjects (category, positions or type) that have no rule in force.
    """

    minimum: Decimal | None
    maximum: Decimal
    rule_id: int
    tied_rule_ids: tuple[int, ...]
    missing: frozenset[Subject]


def _subjects(teacher: TeacherFacts) -> list[Subject]:
    """Return the subjects whose rules decide the teacher's range.

    A full-time teacher depends on their category and each position. A collaborator or a
    competition teacher depends on their type range instead of the category range (D46, D58).

    Raises:
        ValueError: if a teacher that is not full-time has positions.
    """
    if teacher.teacher_type == FULL_TIME:
        return [(RuleKind.CATEGORY, teacher.category_id)] + [
            (RuleKind.POSITION, position) for position in sorted(teacher.position_ids)
        ]
    if teacher.position_ids:
        raise ValueError("Only full-time teachers can hold positions.")
    return [(RuleKind.TEACHER_TYPE, teacher.teacher_type)]


def _rule_in_force(rules: list[RangeRule], subject: Subject, as_of: date) -> RangeRule | None:
    """Return the rule of a subject in force on a date, or ``None``.

    Raises:
        ValueError: if two rules of the subject start on the same day (ambiguous data).
    """
    kind, ref = subject
    started = [r for r in rules if r.kind == kind and r.ref == ref and r.valid_from <= as_of]
    if not started:
        return None
    latest = max(r.valid_from for r in started)
    current = [r for r in started if r.valid_from == latest]
    if len(current) > 1:
        raise ValueError(f"Two rules for {subject} start on {latest}.")
    return current[0]


def _sort_key(rule: RangeRule) -> tuple:
    """Order rules: lowest maximum, then lowest minimum (none is lowest), then fixed order."""
    minimum = Decimal("-1") if rule.minimum is None else rule.minimum
    return (rule.maximum, minimum, _KIND_ORDER[rule.kind], rule.id)


def resolve_load_range(
    rules: Iterable[RangeRule], teacher: TeacherFacts, as_of: date
) -> ResolvedRange | None:
    """Return the range of lesson hours that applies to a teacher on a date.

    For each subject of the teacher (category and positions, or the teacher type) the rule in
    force is found; among them the one with the lowest maximum wins as a whole, with its own
    minimum (D11). Ties on the maximum go to the lowest minimum, with "no minimum" counting as
    the lowest, then to the fixed order position, category, type, then to the lowest id, so the
    answer never depends on the order of the input.

    Args:
        rules: every known rule (of any subject and date).
        teacher: the teacher's type, category and positions.
        as_of: the date the range must be valid on.

    Returns:
        The resolved range, or ``None`` when no rule is in force for any of the teacher's
        subjects (a gap in the data, not an error).

    Raises:
        ValueError: for inconsistent input: positions on a teacher who is not full-time, a rule
            whose minimum is above its maximum, or two rules of one subject starting on the same
            day.
    """
    all_rules = list(rules)
    for rule in all_rules:
        if rule.minimum is not None and rule.minimum > rule.maximum:
            raise ValueError(f"Rule {rule.id} has a minimum above its maximum.")
    subjects = _subjects(teacher)
    current = {s: _rule_in_force(all_rules, s, as_of) for s in subjects}
    found = [r for r in current.values() if r is not None]
    if not found:
        return None
    winner = min(found, key=_sort_key)
    tied = sorted(r.id for r in found if r.maximum == winner.maximum and r.id != winner.id)
    missing = frozenset(s for s, r in current.items() if r is None)
    return ResolvedRange(
        minimum=winner.minimum,
        maximum=winner.maximum,
        rule_id=winner.id,
        tied_rule_ids=tuple(tied),
        missing=missing,
    )
