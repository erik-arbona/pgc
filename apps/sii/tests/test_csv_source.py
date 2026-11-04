"""Tests for the SII import contract and its CSV implementation.

Implements: docs/especificacao/07_arquitetura.md – integrations (the SII medium is still to be
confirmed, so only a contract and a test CSV source exist); 06_exames.md; D29, D66. Nothing is
written to the database. Errors name the line and the column, never the value, because student
names are personal data.
"""

from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.sii.contract import (
    EnrollmentRecord,
    ExamRegistrationRecord,
    ReadResult,
    SiiError,
    SiiNotConfigured,
    SiiSource,
    TeacherRecord,
)
from apps.sii.csv_source import CsvSiiSource
from apps.sii.source import get_source

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

TEACHERS_HEADER = "identifier,name,category\n"
ENROLLMENTS_HEADER = "student_number,course_ref,academic_year,curricular_year\n"
REGISTRATIONS_HEADER = "student_number,student_name,subject_ref,season,academic_year,semester\n"


def write(directory, name, text, encoding="utf-8"):
    """Write a CSV file in a directory."""
    (directory / name).write_text(text, encoding=encoding)


@pytest.fixture
def folder(tmp_path):
    """A folder with the three files, each with only its header."""
    write(tmp_path, "teachers.csv", TEACHERS_HEADER)
    write(tmp_path, "enrollments.csv", ENROLLMENTS_HEADER)
    write(tmp_path, "exam_registrations.csv", REGISTRATIONS_HEADER)
    return tmp_path


# --- the samples ---


def test_the_sample_files_are_read_without_errors():
    """The fictitious samples in the repository are valid and have records of every kind."""
    source = CsvSiiSource(SAMPLES)
    teachers, enrollments, registrations = (
        source.read_teachers(),
        source.read_enrollments(),
        source.read_exam_registrations(),
    )
    assert not (teachers.errors or enrollments.errors or registrations.errors)
    assert teachers.records and enrollments.records and registrations.records
    assert isinstance(teachers.records[0], TeacherRecord)
    assert isinstance(enrollments.records[0], EnrollmentRecord)
    assert isinstance(registrations.records[0], ExamRegistrationRecord)


def test_the_samples_are_clearly_fictitious():
    """No real names in the repository (CLAUDE.md rule 8)."""
    source = CsvSiiSource(SAMPLES)
    assert all(t.name.startswith("Docente") for t in source.read_teachers().records)
    names = [r.student_name for r in source.read_exam_registrations().records]
    assert names and all(name.startswith("Estudante") for name in names)


# --- the contract ---


def test_the_contract_cannot_be_used_directly():
    """SiiSource is abstract: a real source has to implement the three readings."""
    with pytest.raises(TypeError):
        SiiSource()


def test_a_source_that_implements_the_three_readings_is_a_source():
    """Another medium (API, database) only needs these methods."""

    class Fake(SiiSource):
        @classmethod
        def from_settings(cls):
            return cls()

        def read_teachers(self):
            return ReadResult([], [])

        def read_enrollments(self):
            return ReadResult([], [])

        def read_exam_registrations(self):
            return ReadResult([], [])

    assert Fake().read_teachers().records == []


# --- reading valid files ---


def test_teachers_are_read_in_order_and_values_are_trimmed(folder):
    """Whitespace around values is removed and the order of the file is kept."""
    write(
        folder,
        "teachers.csv",
        TEACHERS_HEADER + " DT1 , Docente A , Doutor \nDT2,Docente B,Mestre\n",
    )
    result = CsvSiiSource(folder).read_teachers()
    assert result.records == [
        TeacherRecord("DT1", "Docente A", "Doutor"),
        TeacherRecord("DT2", "Docente B", "Mestre"),
    ]
    assert result.errors == []


@pytest.mark.parametrize("separator", [",", ";"])
def test_both_the_comma_and_the_semicolon_are_accepted(folder, separator):
    """Excel in Portuguese saves CSV with semicolons."""
    text = separator.join(["identifier", "name", "category"]) + "\n"
    text += separator.join(["DT1", "Docente A", "Doutor"]) + "\n"
    write(folder, "teachers.csv", text)
    assert CsvSiiSource(folder).read_teachers().records[0].identifier == "DT1"


def test_a_utf8_file_with_the_excel_byte_order_mark_is_accepted(folder):
    """The BOM does not turn the first column name into something else."""
    write(
        folder,
        "teachers.csv",
        "﻿" + TEACHERS_HEADER + "DT1,Docente Ângela,Doutor\n",
        encoding="utf-8",
    )
    result = CsvSiiSource(folder).read_teachers()
    assert result.records[0].name == "Docente Ângela"


def test_extra_columns_and_blank_lines_are_ignored(folder):
    """The SII file may carry more columns than the contract needs."""
    write(folder, "teachers.csv", "identifier,name,category,email\n\nDT1,Docente A,Doutor,x@y.z\n")
    assert len(CsvSiiSource(folder).read_teachers().records) == 1


def test_enrollments_and_registrations_are_typed(folder):
    """Years and semester become integers."""
    write(folder, "enrollments.csv", ENROLLMENTS_HEADER + "E1,CURSO-A,2026,1\n")
    write(
        folder,
        "exam_registrations.csv",
        REGISTRATIONS_HEADER + "E1,Estudante 1,DISC-1,1.ª chamada,2026,1\n",
    )
    source = CsvSiiSource(folder)
    assert source.read_enrollments().records == [EnrollmentRecord("E1", "CURSO-A", 2026, 1)]
    assert source.read_exam_registrations().records == [
        ExamRegistrationRecord("E1", "Estudante 1", "DISC-1", "1.ª chamada", 2026, 1)
    ]


def test_a_file_with_only_a_header_gives_no_records(folder):
    """Nothing to import is not an error."""
    result = CsvSiiSource(folder).read_enrollments()
    assert result.records == [] and result.errors == []


# --- problems with a whole file ---


def test_a_missing_file_is_an_error(tmp_path):
    """The folder has to contain the file."""
    with pytest.raises(SiiError) as error:
        CsvSiiSource(tmp_path).read_teachers()
    assert "teachers.csv" in str(error.value)


def test_a_missing_folder_is_an_error(tmp_path):
    """A folder that does not exist is refused when reading."""
    with pytest.raises(SiiError):
        CsvSiiSource(tmp_path / "nao_existe").read_teachers()


def test_a_missing_column_is_an_error_naming_only_the_column(folder):
    """The header is checked before any row is read."""
    write(folder, "teachers.csv", "identifier,name\nDT1,Docente A\n")
    with pytest.raises(SiiError) as error:
        CsvSiiSource(folder).read_teachers()
    assert "category" in str(error.value) and "Docente A" not in str(error.value)


# --- problems with some rows ---


def test_bad_rows_are_reported_with_line_and_column_and_the_rest_is_kept(folder):
    """One bad row does not stop the import."""
    write(
        folder,
        "enrollments.csv",
        ENROLLMENTS_HEADER
        + "E1,CURSO-A,2026,1\nE2,CURSO-A,vinte,1\nE3,CURSO-A,2026,0\nE4,CURSO-B,2026,2\n",
    )
    result = CsvSiiSource(folder).read_enrollments()
    assert [r.student_number for r in result.records] == ["E1", "E4"]
    assert [(e.line, e.column) for e in result.errors] == [
        (3, "academic_year"),
        (4, "curricular_year"),
    ]


def test_an_empty_required_value_is_reported(folder):
    """Required values cannot be blank."""
    write(folder, "teachers.csv", TEACHERS_HEADER + "DT1,,Doutor\n")
    result = CsvSiiSource(folder).read_teachers()
    assert result.records == [] and [(e.line, e.column) for e in result.errors] == [(2, "name")]


def test_a_semester_other_than_one_or_two_is_reported(folder):
    """Semesters are 1 or 2."""
    write(
        folder,
        "exam_registrations.csv",
        REGISTRATIONS_HEADER + "E1,Estudante 1,D1,1.ª chamada,2026,3\n",
    )
    result = CsvSiiSource(folder).read_exam_registrations()
    assert [(e.line, e.column) for e in result.errors] == [(2, "semester")]


def test_a_repeated_record_is_reported_and_the_first_is_kept(folder):
    """Duplicates (ignoring case in teacher identifiers) are reported."""
    write(folder, "teachers.csv", TEACHERS_HEADER + "DT1,Docente A,Doutor\ndt1,Docente B,Mestre\n")
    result = CsvSiiSource(folder).read_teachers()
    assert [r.name for r in result.records] == ["Docente A"]
    assert [(e.line, e.column) for e in result.errors] == [(3, "identifier")]


def test_a_row_with_too_many_fields_is_reported(folder):
    """A malformed row is not guessed at."""
    write(folder, "teachers.csv", TEACHERS_HEADER + "DT1,Docente A,Doutor,sobra\n")
    result = CsvSiiSource(folder).read_teachers()
    assert result.records == [] and len(result.errors) == 1


def test_errors_never_contain_the_values_of_the_file(folder):
    """Student names are personal data: the report names line and column only."""
    write(
        folder,
        "exam_registrations.csv",
        REGISTRATIONS_HEADER + "E9,Estudante Segredo,DISC-9,1.ª chamada,abcd,1\n",
    )
    result = CsvSiiSource(folder).read_exam_registrations()
    text = " ".join(f"{e.line} {e.column} {e.message}" for e in result.errors)
    assert result.errors and "Segredo" not in text and "E9" not in text and "DISC-9" not in text


# --- choosing the source ---


def test_the_source_is_not_configured_by_default(settings):
    """Without a folder there is no source: the real SII medium is still to be confirmed."""
    settings.SII_CSV_DIR = ""
    with pytest.raises(SiiNotConfigured):
        get_source()


def test_the_csv_source_is_built_from_the_settings(settings, folder):
    """SII_CSV_DIR selects the folder of the test source."""
    settings.SII_SOURCE = "apps.sii.csv_source.CsvSiiSource"
    settings.SII_CSV_DIR = str(folder)
    assert isinstance(get_source(), CsvSiiSource)


def test_another_source_can_be_selected_by_its_dotted_path(settings):
    """A future API or database source plugs in through SII_SOURCE."""
    settings.SII_SOURCE = "apps.sii.tests.test_csv_source.AlternativeSource"
    assert isinstance(get_source(), AlternativeSource)


def test_an_unknown_source_is_a_configuration_error(settings):
    """A wrong dotted path fails loudly."""
    settings.SII_SOURCE = "apps.sii.nao_existe.Fonte"
    with pytest.raises(ImproperlyConfigured):
        get_source()


class AlternativeSource(SiiSource):
    """A stand-in for a future API source (used by the tests above)."""

    @classmethod
    def from_settings(cls):
        return cls()

    def read_teachers(self):
        return ReadResult([], [])

    def read_enrollments(self):
        return ReadResult([], [])

    def read_exam_registrations(self):
        return ReadResult([], [])
