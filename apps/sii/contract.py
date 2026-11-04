"""The contract for importing data from the SII, independent of how it is fetched.

Implements: docs/especificacao/07_arquitetura.md – integration with the SII (enrolments, teachers
and the students registered in each exam); 06_exames.md; D29, D66. The specification leaves the
medium open (API, database connection or CSV files, to be confirmed), so the rest of the
application depends on this contract and a source only has to implement it. Pure Python.

The record fields are provisional: the real SII may ask for changes (D66). Course and subject
references are opaque SII values; mapping them to PGC courses and subjects comes later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class SiiError(Exception):
    """The SII data cannot be read at all (missing file, unreadable file, missing column)."""


class SiiNotConfigured(SiiError):
    """No SII source is configured: the real medium is still to be confirmed."""


@dataclass(frozen=True)
class TeacherRecord:
    """A teacher as the SII knows them.

    Attributes:
        identifier: the teacher's unique identifier.
        name: full name.
        category: scientific degree, as the SII writes it.
    """

    identifier: str
    name: str
    category: str


@dataclass(frozen=True)
class EnrollmentRecord:
    """The enrolment of a student in a course for an academic year.

    Attributes:
        student_number: the student's number; the enrolments give the size of each turma.
        course_ref: opaque SII reference of the course.
        academic_year: start year of the academic year (2026 for 2026/2027).
        curricular_year: year of the course, starting at 1.
    """

    student_number: str
    course_ref: str
    academic_year: int
    curricular_year: int


@dataclass(frozen=True)
class ExamRegistrationRecord:
    """The registration of a student in the exam of a subject and season.

    The name is included because the coordinator consults the list (D29); it is personal data.

    Attributes:
        student_number: the student's number.
        student_name: the student's name.
        subject_ref: opaque SII reference of the subject.
        season: the exam season as the SII writes it (for example "1.ª chamada").
        academic_year: start year of the academic year.
        semester: 1 or 2.
    """

    student_number: str
    student_name: str
    subject_ref: str
    season: str
    academic_year: int
    semester: int


@dataclass(frozen=True)
class RowError:
    """A problem in one row of the source.

    It names the line and the column and never repeats the value: the data includes personal
    data of students.

    Attributes:
        line: the line of the file (the header is line 1).
        column: the column with the problem.
        message: what is wrong, without the value.
    """

    line: int
    column: str
    message: str


@dataclass
class ReadResult[T]:
    """The outcome of reading one kind of data: the valid records and the problems found."""

    records: list[T] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


class SiiSource(ABC):
    """A source of SII data: a CSV folder today, perhaps an API or a database later."""

    @classmethod
    @abstractmethod
    def from_settings(cls) -> SiiSource:
        """Build the source from the Django settings.

        Raises:
            SiiNotConfigured: if the settings do not say where the data is.
        """

    @abstractmethod
    def read_teachers(self) -> ReadResult[TeacherRecord]:
        """Read the teachers.

        Raises:
            SiiError: if the data cannot be read at all.
        """

    @abstractmethod
    def read_enrollments(self) -> ReadResult[EnrollmentRecord]:
        """Read the enrolments by course.

        Raises:
            SiiError: if the data cannot be read at all.
        """

    @abstractmethod
    def read_exam_registrations(self) -> ReadResult[ExamRegistrationRecord]:
        """Read the students registered in each exam.

        Raises:
            SiiError: if the data cannot be read at all.
        """
