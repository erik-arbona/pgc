"""Choose the SII source from the settings.

Implements: docs/especificacao/07_arquitetura.md – the SII medium is still to be confirmed (D66).
``SII_SOURCE`` is the dotted path of a ``SiiSource`` class (the CSV test source by default); a
future API or database source plugs in here without touching the rest of the application.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .contract import SiiSource


def get_source() -> SiiSource:
    """Return the configured SII source.

    Returns:
        An instance of the class named by ``SII_SOURCE``, built with its ``from_settings``.

    Raises:
        ImproperlyConfigured: if ``SII_SOURCE`` does not name a ``SiiSource`` class.
        SiiNotConfigured: if the source needs settings that are empty (for the CSV source,
            ``SII_CSV_DIR``).
    """
    path = getattr(settings, "SII_SOURCE", "apps.sii.csv_source.CsvSiiSource")
    try:
        source_class = import_string(path)
    except ImportError as error:
        raise ImproperlyConfigured(f"SII_SOURCE {path!r} cannot be imported.") from error
    if not (isinstance(source_class, type) and issubclass(source_class, SiiSource)):
        raise ImproperlyConfigured(f"SII_SOURCE {path!r} is not a SiiSource class.")
    return source_class.from_settings()
