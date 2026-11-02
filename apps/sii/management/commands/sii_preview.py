"""Preview a folder of SII CSV files without saving anything.

Implements: D66. It only reads and reports, so a file can be checked (for example with Serviços
Académicos) before any real integration exists. Problems are shown by line and column, never with
the values of the file, because it holds personal data of students.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.sii.contract import SiiError
from apps.sii.csv_source import CsvSiiSource


class Command(BaseCommand):
    """Read the three CSV files of a folder and print counts and problems."""

    help = "Preview a folder of SII CSV files: sii_preview <folder>. Saves nothing."

    def add_arguments(self, parser) -> None:
        """Declare the arguments."""
        parser.add_argument(
            "folder", help="Folder with teachers.csv, enrollments.csv and exam_registrations.csv."
        )

    def handle(self, *args, **options) -> None:
        """Print one line per file and then the problems found.

        Raises:
            CommandError: if a file is missing, unreadable or lacks a required column.
        """
        source = CsvSiiSource(options["folder"])
        readings = (
            ("teachers", "teachers.csv", source.read_teachers),
            ("enrollments", "enrollments.csv", source.read_enrollments),
            ("exam_registrations", "exam_registrations.csv", source.read_exam_registrations),
        )
        problems = []
        for label, filename, read in readings:
            try:
                result = read()
            except SiiError as error:
                raise CommandError(str(error)) from None
            self.stdout.write(
                f"{label}: {len(result.records)} records, {len(result.errors)} errors"
            )
            problems += [f"  {filename}:{e.line} {e.column} {e.message}" for e in result.errors]
        if problems:
            self.stdout.write("Problems:")
            self.stdout.write("\n".join(problems))
