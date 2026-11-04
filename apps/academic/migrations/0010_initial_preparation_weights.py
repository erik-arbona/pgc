"""Set the preparation weights of the initial class types (the formula of the specification).

Preparation = T + (TP + P + L) x 1.5, so T weighs 1 and TP, P and L weigh 1.5; 'other' weighs 0
because the formula does not mention it. See D61.
"""

from decimal import Decimal

from django.db import migrations

WEIGHTS = {
    "T": Decimal("1"),
    "TP": Decimal("1.5"),
    "P": Decimal("1.5"),
    "L": Decimal("1.5"),
    "OUT": Decimal("0"),
}


def set_weights(apps, schema_editor):
    """Give each initial class type its weight; types that do not exist are skipped."""
    ClassType = apps.get_model("academic", "ClassType")
    for code, weight in WEIGHTS.items():
        ClassType.objects.filter(code=code).update(preparation_weight=weight)


class Migration(migrations.Migration):
    dependencies = [("academic", "0009_class_type_preparation_weight")]

    # Reverse is a no-op: the weights are configurable data the manager may have changed.
    operations = [migrations.RunPython(set_weights, migrations.RunPython.noop)]
