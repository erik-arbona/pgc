"""Load the system parameters. See D60."""

from decimal import Decimal

from django.db import migrations

INITIAL_PARAMETERS = [
    # Teaching weeks in each semester, as stated by the PGC manager (D60).
    ("semester_weeks", "Semanas por semestre", Decimal("15")),
]


def load_parameters(apps, schema_editor):
    """Create the parameters, leaving any that already exist untouched."""
    Parameter = apps.get_model("core", "Parameter")
    for code, name, value in INITIAL_PARAMETERS:
        Parameter.objects.get_or_create(code=code, defaults={"name": name, "value": value})


class Migration(migrations.Migration):
    dependencies = [("core", "0004_parameter")]

    # Reverse is a no-op: other code may already depend on the parameters.
    operations = [migrations.RunPython(load_parameters, migrations.RunPython.noop)]
