"""Domain rule: weekly preparation hours of a subject.

Implements: docs/especificacao/05_dsd_regras.md – preparation = theoretical weekly hours +
(theoretical-practical, practical and laboratory weekly hours) x 1.5, kept as a parameter so
that it can be adjusted without touching the code; D14, D61. Pure Python: no Django.

The parameter is a weight per class type (``ClassType.preparation_weight``): with T = 1 and
TP = P = L = 1.5 the rule is exactly the formula of the specification, and a class type the
manager creates later counts as soon as it has a weight.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal


def preparation_hours(
    weekly_hours: Mapping[str, Decimal], weights: Mapping[str, Decimal]
) -> Decimal:
    """Return the weekly preparation hours for the weekly hours of each class type.

    Args:
        weekly_hours: weekly hours keyed by class type code.
        weights: preparation weight of each class type, keyed by code.

    Returns:
        The sum of each class type's hours times its weight; zero when there are no hours.

    Raises:
        ValueError: if a class type with hours has no weight (never a silent zero), or if an
            hour or a weight is negative.
    """
    total = Decimal("0")
    for code, hours in weekly_hours.items():
        if hours < 0:
            raise ValueError(f"Negative hours for {code}.")
        if code not in weights:
            raise ValueError(f"No preparation weight for class type {code}.")
        if weights[code] < 0:
            raise ValueError(f"Negative preparation weight for {code}.")
        total += hours * weights[code]
    return total
