"""Load the initial class types (T, TP, P, L, other). See D45."""

from django.db import migrations

INITIAL_TYPES = [
    ("T", "Teórica", 10),
    ("TP", "Teórico-prática", 20),
    ("P", "Prática", 30),
    ("L", "Laboratorial", 40),
    ("OUT", "Outra", 50),
]


def load_types(apps, schema_editor):
    """Create the initial types, leaving any type that already exists untouched."""
    ClassType = apps.get_model("academic", "ClassType")
    for code, name, position in INITIAL_TYPES:
        ClassType.objects.get_or_create(code=code, defaults={"name": name, "position": position})


class Migration(migrations.Migration):
    dependencies = [("academic", "0003_class_type_config")]

    # Reverse is a no-op: types may already be referenced by subjects.
    operations = [migrations.RunPython(load_types, migrations.RunPython.noop)]
