"""A SII source that reads CSV files from a folder (the test implementation).

Implements: docs/especificacao/07_arquitetura.md – the SII medium is still to be confirmed, so
this source exists to test the contract with files; T5.1, D66. It reads three files:
``teachers.csv``, ``enrollments.csv`` and ``exam_registrations.csv``. Their column names are
provisional. It accepts the comma or the semicolon (Excel in Portuguese) and the UTF-8 byte order
mark, ignores extra columns and blank lines, and reports each bad row with its line and column
without repeating the value.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from django.conf import settings

from .contract import (
    EnrollmentRecord,
    ExamRegistrationRecord,
    ReadResult,
    RowError,
    SiiError,
    SiiNotConfigured,
    SiiSource,
    TeacherRecord,
)

T = TypeVar("T")


class _RowProblem(Exception):
    """A row is invalid; carries the column and a message (never the value)."""

    def __init__(self, column: str, message: str) -> None:
        super().__init__(message)
        self.column = column
        self.message = message


def _text(row: dict, column: str) -> str:
    """Return a required text value, trimmed."""
    value = (row.get(column) or "").strip()
    if not value:
        raise _RowProblem(column, "is required")
    return value


def _integer(row: dict, column: str, minimum: int, maximum: int | None = None) -> int:
    """Return a required whole number within limits."""
    raw = _text(row, column)
    if not (raw.isascii() and raw.isdigit()):
        raise _RowProblem(column, "must be a whole number")
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        raise _RowProblem(column, "is out of range")
    return value


def _teacher(row: dict) -> TeacherRecord:
    """Build a teacher record from a row."""
    return TeacherRecord(_text(row, "identifier"), _text(row, "name"), _text(row, "category"))


def _enrollment(row: dict) -> EnrollmentRecord:
    """Build an enrolment record from a row."""
    return EnrollmentRecord(
        _text(row, "student_number"),
        _text(row, "course_ref"),
        _integer(row, "academic_year", 2000, 2100),
        _integer(row, "curricular_year", 1),
    )


def _registration(row: dict) -> ExamRegistrationRecord:
    """Build an exam registration record from a row."""
    return ExamRegistrationRecord(
        _text(row, "student_number"),
        _text(row, "student_name"),
        _text(row, "subject_ref"),
        _text(row, "season"),
        _integer(row, "academic_year", 2000, 2100),
        _integer(row, "semester", 1, 2),
    )


def _teacher_key(record: TeacherRecord) -> tuple:
    """Teachers are unique by identifier, ignoring case."""
    return (record.identifier.casefold(),)


def _enrollment_key(record: EnrollmentRecord) -> tuple:
    """An enrolment is identified by student, course and academic year."""
    return (record.student_number, record.course_ref, record.academic_year)


def _registration_key(record: ExamRegistrationRecord) -> tuple:
    """A registration is identified by student, subject, season, year and semester."""
    return (
        record.student_number,
        record.subject_ref,
        record.season,
        record.academic_year,
        record.semester,
    )


class CsvSiiSource(SiiSource):
    """Reads the SII data from three CSV files in a folder."""

    def __init__(self, directory: str | Path) -> None:
        """Remember the folder; nothing is read until a ``read_*`` method is called."""
        self.directory = Path(directory)

    @classmethod
    def from_settings(cls) -> CsvSiiSource:
        """Build the source from ``SII_CSV_DIR``.

        Raises:
            SiiNotConfigured: if ``SII_CSV_DIR`` is empty.
        """
        directory = getattr(settings, "SII_CSV_DIR", "")
        if not directory:
            raise SiiNotConfigured("SII_CSV_DIR is not set: the SII source is not configured.")
        return cls(directory)

    def read_teachers(self) -> ReadResult[TeacherRecord]:
        """Read ``teachers.csv``."""
        return self._read(
            "teachers.csv", ("identifier", "name", "category"), _teacher, _teacher_key
        )

    def read_enrollments(self) -> ReadResult[EnrollmentRecord]:
        """Read ``enrollments.csv``."""
        columns = ("student_number", "course_ref", "academic_year", "curricular_year")
        return self._read("enrollments.csv", columns, _enrollment, _enrollment_key)

    def read_exam_registrations(self) -> ReadResult[ExamRegistrationRecord]:
        """Read ``exam_registrations.csv``."""
        columns = (
            "student_number",
            "student_name",
            "subject_ref",
            "season",
            "academic_year",
            "semester",
        )
        return self._read("exam_registrations.csv", columns, _registration, _registration_key)

    def _read(
        self,
        filename: str,
        columns: tuple[str, ...],
        build: Callable[[dict], T],
        key: Callable[[T], tuple],
    ) -> ReadResult[T]:
        """Read one file into records and row errors.

        Raises:
            SiiError: if the file is missing or unreadable, or a required column is missing.
        """
        path = self.directory / filename
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise SiiError(f"Missing file: {filename}") from None
        except (OSError, UnicodeDecodeError):
            raise SiiError(f"Cannot read file: {filename}") from None
        lines = text.splitlines()
        header = lines[0] if lines else ""
        delimiter = ";" if header.count(";") > header.count(",") else ","
        reader = csv.DictReader(lines, delimiter=delimiter, restkey="_extra")
        names = [(name or "").strip() for name in (reader.fieldnames or [])]
        reader.fieldnames = names
        missing = [column for column in columns if column not in names]
        if missing:
            raise SiiError(f"{filename} lacks the column(s): {', '.join(missing)}")
        result: ReadResult[T] = ReadResult()
        seen: set[tuple] = set()
        for row in reader:
            line = reader.line_num
            try:
                if "_extra" in row:
                    raise _RowProblem("_row", "has more fields than the header")
                record = build(row)
                record_key = key(record)
                if record_key in seen:
                    raise _RowProblem(columns[0], "repeats an earlier record")
            except _RowProblem as problem:
                result.errors.append(RowError(line, problem.column, problem.message))
                continue
            seen.add(record_key)
            result.records.append(record)
        return result
