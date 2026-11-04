"""Tests for the modular project structure.

Implements: docs/especificacao/07_arquitetura.md – one Django app per functional block.
"""

import pytest
from django.apps import apps

EXPECTED_APPS = ["core", "academic", "staff", "rooms", "demo", "sii"]


@pytest.mark.parametrize("label", EXPECTED_APPS)
def test_phase_one_apps_are_installed_under_the_apps_package(label):
    """Each phase-1 app is installed and lives in the ``apps`` package."""
    config = apps.get_app_config(label)
    assert config.name == f"apps.{label}"
