"""Load the real study plans of EIC and TM for development.

Implements: D78 (the plans in ``docs/Planos_EIC_TM.md`` may be in the repository), D79 (tracks).
Safe to run twice (it only creates what is missing) and it never deletes anything. It refuses to
run unless DEBUG is on, or ``--force`` is given.

The Faculty of the courses and the coordination of each subject are not in the plans: give them
with ``--faculty`` and ``--coordination``, or use ``--placeholders`` to create a Faculty and a
coordination that say they must be confirmed. The start years of the plans are assumptions
(``--eic-year``, ``--tm-year``). The UCT of the last semester (Q27) and the optional subjects
behind the "Opção Condicionada" slot (Q28) are not loaded and are listed in the output.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.academic.models import Coordination, Faculty
from apps.core.audit import audited_save
from apps.core.parameters import SEMESTER_WEEKS, get_parameter
from apps.demo.real_plan_loader import (
    DEFAULT_PLAN_YEARS,
    PLACEHOLDER_COORDINATION_NAME,
    PLACEHOLDER_FACULTY_CODE,
    PLACEHOLDER_FACULTY_NAME,
    RealPlanLoader,
)
from apps.demo.real_plans import parse_plans, resolve_subjects

DEFAULT_FILE = Path(settings.BASE_DIR) / "docs" / "Planos_EIC_TM.md"


class Command(BaseCommand):
    """Create the courses, plans, tracks and subjects of the real EIC and TM plans."""

    help = "Load the real study plans (docs/Planos_EIC_TM.md). Development only."

    def add_arguments(self, parser) -> None:
        """Declare the arguments."""
        parser.add_argument(
            "--file", default=str(DEFAULT_FILE), help="Markdown file with the plans."
        )
        parser.add_argument("--faculty", help="Code of the existing Faculty of the courses.")
        parser.add_argument(
            "--coordination", help="Name of the existing coordination of the subjects."
        )
        parser.add_argument(
            "--placeholders",
            action="store_true",
            help="Create a marked Faculty and coordination instead of giving existing ones.",
        )
        parser.add_argument("--eic-year", type=int, default=DEFAULT_PLAN_YEARS["EIC"])
        parser.add_argument("--tm-year", type=int, default=DEFAULT_PLAN_YEARS["TM"])
        parser.add_argument(
            "--turmas", action="store_true", help="Also create example turmas (cohort and tracks)."
        )
        parser.add_argument("--force", action="store_true", help="Run even if DEBUG is off.")

    def handle(self, *args, **options) -> None:
        """Parse the file and load it in one transaction.

        Raises:
            CommandError: if DEBUG is off and ``--force`` was not given, if the Faculty and
                coordination are neither given nor allowed as placeholders, if the given ones do
                not exist, or if the file is inconsistent.
        """
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to load with DEBUG off; use --force if you are sure.")
        if not options["placeholders"] and not (options["faculty"] and options["coordination"]):
            raise CommandError(
                "Give --faculty and --coordination, or --placeholders to create marked ones."
            )
        try:
            text = Path(options["file"]).read_text(encoding="utf-8")
            parsed = parse_plans(text, get_parameter(SEMESTER_WEEKS))
            subjects = resolve_subjects(parsed)
        except (OSError, ValueError) as error:
            raise CommandError(f"Cannot read the plans: {error}") from error
        years = {"EIC": options["eic_year"], "TM": options["tm_year"]}
        with transaction.atomic():
            faculty, coordination = self._faculty_and_coordination(options)
            loader = RealPlanLoader(faculty, coordination, years, with_turmas=options["turmas"])
            loader.load(parsed, subjects)
        self._report(loader, parsed, subjects, options["placeholders"])

    def _faculty_and_coordination(self, options) -> tuple[Faculty, Coordination]:
        """Return the given Faculty and coordination, or create the marked placeholders."""
        if options["placeholders"]:
            faculty, _ = Faculty.objects.get_or_create(
                code=PLACEHOLDER_FACULTY_CODE, defaults={"name": PLACEHOLDER_FACULTY_NAME}
            )
            coordination = Coordination.objects.filter(
                faculty=faculty, name=PLACEHOLDER_COORDINATION_NAME
            ).first()
            if coordination is None:
                coordination = Coordination(faculty=faculty, name=PLACEHOLDER_COORDINATION_NAME)
                audited_save(coordination, None, "")
            return faculty, coordination
        try:
            faculty = Faculty.objects.get(code=options["faculty"])
            coordination = Coordination.objects.get(faculty=faculty, name=options["coordination"])
        except (Faculty.DoesNotExist, Coordination.DoesNotExist) as error:
            raise CommandError("The Faculty or the coordination given does not exist.") from error
        return faculty, coordination

    def _report(self, loader, parsed, subjects, placeholders: bool) -> None:
        """Print what was created, what was not loaded and what must be reviewed."""
        created = ", ".join(f"{count} {kind}" for kind, count in loader.created.items())
        self.stdout.write(f"Created: {created or 'nothing (already loaded)'}.")
        self.stdout.write(f"Subjects in the plans: {len(subjects)}.")
        uct = [s for s in parsed.skipped if s.kind == "uct"]
        optional = [s for s in parsed.skipped if s.kind == "optional"]
        self.stdout.write(f"Not loaded, UCT of the last semester (Q27): {len(uct)} tables.")
        for item in uct:
            self.stdout.write(f"  UCT {item.description}")
        self.stdout.write("Not loaded, optional subjects of the 'Opção Condicionada' (Q28):")
        for item in optional:
            self.stdout.write(f"  {item.course}: {item.description}")
        self.stdout.write(
            f"Plan start years: {loader.years} (the TM year is an assumption). "
            "Subject codes are placeholders."
        )
        if placeholders:
            self.stdout.write(
                "Review: every subject uses the placeholder coordination "
                f"'{PLACEHOLDER_COORDINATION_NAME}' in Faculty '{PLACEHOLDER_FACULTY_NAME}'."
            )
