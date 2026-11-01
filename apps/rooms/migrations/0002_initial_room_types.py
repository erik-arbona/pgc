"""Load the initial room types named by the user: classroom, laboratory and auditorium. See D63.

The list is configurable: Património can add, rename or deactivate types ('etc.').
"""

from django.db import migrations

INITIAL_TYPES = [
    ("SALA", "Sala de aula", 10),
    ("LAB", "Laboratório", 20),
    ("AUD", "Auditório", 30),
]


def load_types(apps, schema_editor):
    """Create the initial types, leaving any that already exist untouched."""
    RoomType = apps.get_model("rooms", "RoomType")
    for code, name, position in INITIAL_TYPES:
        RoomType.objects.get_or_create(code=code, defaults={"name": name, "position": position})


class Migration(migrations.Migration):
    dependencies = [("rooms", "0001_initial")]

    # Reverse is a no-op: types may already be referenced by rooms.
    operations = [migrations.RunPython(load_types, migrations.RunPython.noop)]
