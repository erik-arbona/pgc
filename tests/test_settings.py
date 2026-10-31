"""Tests for the environment-driven project settings.

Implements: docs/especificacao/07_arquitetura.md – components (Django, PostgreSQL, Redis).
"""

import importlib

import pytest
from django.db import connection


def _reload_settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Reload ``config.settings`` with the given environment variables.

    Args:
        monkeypatch: pytest fixture used to set the environment.
        **env: environment variables to set before the reload.

    Returns:
        The freshly imported settings module.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config.settings as settings

    return importlib.reload(settings)


def test_secret_key_and_debug_are_read_from_environment(monkeypatch):
    """SECRET_KEY and DEBUG come from the environment, never from code."""
    settings = _reload_settings(monkeypatch, DJANGO_SECRET_KEY="from-env", DJANGO_DEBUG="1")
    assert settings.SECRET_KEY == "from-env"
    assert settings.DEBUG is True


def test_debug_is_off_by_default(monkeypatch):
    """Without DJANGO_DEBUG the application runs with debug disabled."""
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    settings = _reload_settings(monkeypatch, DJANGO_SECRET_KEY="x")
    assert settings.DEBUG is False


def test_database_settings_are_read_from_environment(monkeypatch):
    """Database name, user, host and port are configured through the environment."""
    settings = _reload_settings(
        monkeypatch,
        DJANGO_SECRET_KEY="x",
        POSTGRES_DB="db1",
        POSTGRES_USER="u1",
        POSTGRES_PASSWORD="p1",
        POSTGRES_HOST="h1",
        POSTGRES_PORT="5433",
    )
    db = settings.DATABASES["default"]
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert (db["NAME"], db["USER"], db["PASSWORD"], db["HOST"], db["PORT"]) == (
        "db1",
        "u1",
        "p1",
        "h1",
        "5433",
    )


def test_locale_is_european_portuguese_with_translation_enabled(monkeypatch):
    """The interface language is pt-PT and gettext is enabled (see CLAUDE.md conventions)."""
    settings = _reload_settings(monkeypatch, DJANGO_SECRET_KEY="x")
    assert settings.LANGUAGE_CODE == "pt-pt"
    assert settings.USE_I18N is True
    assert settings.TIME_ZONE == "Atlantic/Cape_Verde"


@pytest.mark.django_db
def test_database_connection_works():
    """The configured PostgreSQL database accepts queries."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
