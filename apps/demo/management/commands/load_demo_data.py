"""Load the fictitious data set for development.

Implements: docs/dados_ficticios.md; CLAUDE.md rule 8 (no real data in the repository); D65.
Safe to run twice (it only creates what is missing) and it never deletes anything. It refuses to
run unless DEBUG is on, or ``--force`` is given; outside development the demo accounts are
created without a password (D41).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.identity import local_login_allowed
from apps.demo.loader import ACCOUNTS, DEMO_PASSWORD, DemoLoader


class Command(BaseCommand):
    """Create the fictitious Faculties, courses, subjects, teachers, rooms and accounts."""

    help = "Load the fictitious data set (docs/dados_ficticios.md). Development only."

    def add_arguments(self, parser) -> None:
        """Declare the arguments."""
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even if DEBUG is off; the demo accounts are then created without a password.",
        )

    def handle(self, *args, **options) -> None:
        """Load the data in one transaction and print how to log in.

        Raises:
            CommandError: if DEBUG is off and ``--force`` was not given.
        """
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Refusing to load fictitious data with DEBUG off; use --force if you are sure."
            )
        passwords = local_login_allowed()
        loader = DemoLoader(passwords=passwords)
        with transaction.atomic():
            loader.load()
        created = ", ".join(f"{count} {kind}" for kind, count in loader.created.items())
        self.stdout.write(f"Created: {created or 'nothing (already loaded)'}.")
        self.stdout.write("Demo accounts:")
        for username, _first, _last, profile, *_rest in ACCOUNTS:
            login = f"{username} / {DEMO_PASSWORD}" if passwords else f"{username} (no password)"
            self.stdout.write(f"  {login}  [{profile}]")
