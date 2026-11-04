"""Access to the configurable system parameters.

Implements: CLAUDE.md rule 6 (parameters, not constants); D60.
"""

from __future__ import annotations

from decimal import Decimal

from .models import Parameter

SEMESTER_WEEKS = "semester_weeks"
"""Code of the parameter with the number of teaching weeks in each semester (D60)."""


def get_parameter(code: str) -> Decimal:
    """Return the current value of a parameter.

    Args:
        code: the parameter code, such as ``SEMESTER_WEEKS``.

    Returns:
        The value.

    Raises:
        LookupError: if the parameter does not exist (fail closed, never a silent default).
    """
    try:
        return Parameter.objects.get(code=code).value
    except Parameter.DoesNotExist:
        raise LookupError(f"Unknown parameter: {code}") from None
