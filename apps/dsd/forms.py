"""Forms of the DSD screens (T2.1).

Implements: docs/backlog_fase2.md T2.1.
"""

from apps.core.generic import ReasonModelForm

from .models import Dsd


class DsdForm(ReasonModelForm):
    """Choose the academic year of the new DSD.

    The uniqueness is not validated here: ``create_dsd`` refuses a second DSD with a clear
    message, also when two managers create it at the same time (D43).
    """

    class Meta:
        model = Dsd
        fields = ["academic_year"]

    def validate_unique(self) -> None:
        """Skip Django's generic unique message; the service gives the clear one."""
