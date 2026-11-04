"""Tests for the modular project structure.

Implements: docs/especificacao/07_arquitetura.md – one Django app per functional block.
"""

import pytest
from django.apps import apps

EXPECTED_APPS = ["core", "academic", "staff", "rooms"]


@pytest.mark.parametrize("label", EXPECTED_APPS)
def test_phase_one_apps_are_installed_under_the_apps_package(label):
    """Each phase-1 app is installed and lives in the ``apps`` package."""
    config = apps.get_app_config(label)
    assert config.name == f"apps.{label}"


@pytest.mark.parametrize("label", EXPECTED_APPS)
def test_phase_one_apps_define_no_models_yet(label):
    """T0.2 creates empty apps: no models until the later backlog tasks."""
    assert list(apps.get_app_config(label).get_models()) == []
