"""Load the initial teacher categories (scientific degrees). See D56."""

from django.db import migrations

INITIAL_CATEGORIES = [
    ("LIC", "Licenciado", 10),
    ("MES", "Mestre", 20),
    ("DOU", "Doutor", 30),
]


def load_categories(apps, schema_editor):
    """Create the initial categories, leaving any that already exist untouched."""
    Category = apps.get_model("staff", "Category")
    for code, name, position in INITIAL_CATEGORIES:
        Category.objects.get_or_create(code=code, defaults={"name": name, "position": position})


class Migration(migrations.Migration):
    dependencies = [("staff", "0001_initial")]

    # Reverse is a no-op: categories may already be referenced by teachers.
    operations = [migrations.RunPython(load_categories, migrations.RunPython.noop)]
