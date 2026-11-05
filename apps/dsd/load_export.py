"""CSV export of the load of the teachers of a coordination (T6.4).

Implements: docs/backlog_fase2.md T6.4 (the check against the Excel files, Porta 1); D69; D101.

The figures are those of the live load shown on the overview (``coordination_overview``), so the
file says what the screen says. It has numbers and the state only: no reasons or comments of the
Executive Board. The format is made for an Excel in Portuguese: ``;`` as separator, a decimal
comma and UTF-8 with a byte-order mark, so that accents and columns open without an import wizard.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from .coordination_overview import CoordinationOverview
from .load_facts import status_text

HEADER = (
    "Identificador",
    "Nome",
    "Coordenação",
    "Categoria",
    "Tipo",
    "Horas letivas 1.º semestre",
    "Horas letivas 2.º semestre",
    "Horas letivas anuais",
    "Mínimo",
    "Máximo",
    "Estado",
    "Horas extra",
    "Preparação 1.º semestre",
    "Preparação 2.º semestre",
    "Outras atividades 1.º semestre",
    "Outras atividades 2.º semestre",
    "Total geral",
    "Outra coordenação",
)

# A cell starting with one of these is read by a spreadsheet as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
TWO_PLACES = Decimal("0.01")


def format_number(value: Decimal | None) -> str:
    """Write a number the way a Portuguese Excel reads it: two places and a decimal comma.

    Args:
        value: the number, or ``None`` for an empty cell.

    Returns:
        For example ``10,50``; an empty text for ``None``.
    """
    if value is None:
        return ""
    return str(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)).replace(".", ",")


def csv_text(value: str | None) -> str:
    """Neutralise a text that a spreadsheet would run as a formula (spreadsheet injection).

    Args:
        value: the text of a cell.

    Returns:
        The text unchanged, or prefixed with an apostrophe when it starts with ``=``, ``+``,
        ``-``, ``@``, a tab or a carriage return. ``None`` gives an empty text.
    """
    text = value or ""
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def export_rows(overview: CoordinationOverview) -> list[list[str]]:
    """Build the rows of the export, one per teacher, from the overview of a coordination.

    Args:
        overview: the overview (live load of each teacher, D70-D74, D95).

    Returns:
        The rows in the order of ``HEADER``, as text.
    """
    rows = []
    for row in overview.rows:
        teacher = row.teacher
        assessment = row.load.assessment
        resolved = assessment.range
        rows.append(
            [
                csv_text(teacher.identifier),
                csv_text(teacher.name),
                csv_text(teacher.coordination.name),
                csv_text(teacher.category.name),
                csv_text(teacher.get_teacher_type_display()),
                format_number(assessment.semester_weekly_hours[0]),
                format_number(assessment.semester_weekly_hours[1]),
                format_number(assessment.weekly_hours),
                format_number(resolved.minimum if resolved else None),
                format_number(resolved.maximum if resolved else None),
                csv_text(status_text(assessment, show_extra=False)),
                format_number(assessment.extra_hours),
                format_number(row.load.preparation[0]),
                format_number(row.load.preparation[1]),
                format_number(row.load.other_hours[0]),
                format_number(row.load.other_hours[1]),
                format_number(row.load.general_total),
                "sim" if row.foreign else "",
            ]
        )
    return rows


def render_csv(rows: Iterable[Iterable[str]], header: Iterable[str] | None = None) -> bytes:
    """Write rows as CSV for an Excel in Portuguese.

    Args:
        rows: the rows, as text.
        header: an optional first row.

    Returns:
        UTF-8 with a byte-order mark, ``;`` as separator and CRLF between rows.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    if header is not None:
        writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")
