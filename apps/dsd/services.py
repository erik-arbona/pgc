"""Use cases of the DSD: create the DSD of an academic year (T2.1).

Implements: docs/backlog_fase2.md T2.1; D43 (one DSD per academic year, created by the manager).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.academic.models import AcademicYear
from apps.core.audit import audited_save

from .models import Dsd, DsdSemester

SEMESTER_NUMBERS = (1, 2)


def _existing_dsd(academic_year: AcademicYear) -> Dsd | None:
    """Return the DSD of the academic year, or ``None`` (the friendly pre-check)."""
    return Dsd.objects.filter(academic_year=academic_year).first()


def _already_exists(academic_year: AcademicYear) -> ValidationError:
    """Build the error shown when the academic year already has a DSD."""
    return ValidationError(
        _("Já existe um DSD para o ano letivo %(year)s.") % {"year": academic_year.label}
    )


def create_dsd(academic_year: AcademicYear, actor, reason: str = "") -> Dsd:
    """Create the DSD of an academic year, with its two semesters, in one transaction.

    The unique constraint on ``Dsd.academic_year`` is the real guard: the pre-check only gives
    the friendly message, and a request that loses the race with another manager hits the
    constraint and gets the same message (D43).

    Args:
        academic_year: the academic year.
        actor: the user creating it (audited).
        reason: optional reason (D40).

    Returns:
        The new DSD.

    Raises:
        ValidationError: if the academic year already has a DSD.
    """
    if _existing_dsd(academic_year) is not None:
        raise _already_exists(academic_year)
    try:
        with transaction.atomic():
            dsd = Dsd(academic_year=academic_year)
            audited_save(dsd, actor, reason)
            for number in SEMESTER_NUMBERS:
                audited_save(DsdSemester(dsd=dsd, number=number), actor, reason)
    except IntegrityError:
        raise _already_exists(academic_year) from None
    return dsd
