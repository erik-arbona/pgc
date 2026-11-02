"""Tests for the command that previews a SII CSV folder without saving anything.

Implements: D66. The command only reads and reports, so Serviços Académicos can check a test file
before any real integration exists.
"""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import AuditEntry
from apps.staff.models import Teacher

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def run(*args):
    """Run the command and return what it printed."""
    out = StringIO()
    call_command("sii_preview", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_it_reports_the_counts_of_each_file():
    """The summary has a line per file with its number of records and errors."""
    text = run(str(SAMPLES))
    assert "teachers" in text and "enrollments" in text and "exam_registrations" in text
    assert "0 errors" in text


@pytest.mark.django_db
def test_it_saves_nothing_to_the_database():
    """Previewing never creates teachers or audit entries."""
    run(str(SAMPLES))
    assert not Teacher.objects.exists() and not AuditEntry.objects.exists()


def test_it_lists_the_bad_rows_by_line_and_column(tmp_path):
    """Problems are shown with their position, without the values."""
    (tmp_path / "teachers.csv").write_text(
        "identifier,name,category\nDT1,,Doutor\n", encoding="utf-8"
    )
    (tmp_path / "enrollments.csv").write_text(
        "student_number,course_ref,academic_year,curricular_year\n", encoding="utf-8"
    )
    (tmp_path / "exam_registrations.csv").write_text(
        "student_number,student_name,subject_ref,season,academic_year,semester\n", encoding="utf-8"
    )
    text = run(str(tmp_path))
    assert "teachers.csv:2" in text and "name" in text and "1 errors" in text


def test_a_missing_folder_is_a_command_error(tmp_path):
    """A clear error instead of a traceback."""
    with pytest.raises(CommandError):
        run(str(tmp_path / "nao_existe"))
