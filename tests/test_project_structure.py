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


@pytest.mark.parametrize("label", ["academic", "staff", "rooms"])
def test_apps_without_backlog_tasks_yet_define_no_models(label):
    """Apps whose models belong to later tasks (T2.x, T3.x, T4.x) are still empty.

    ``core`` is excluded: it gained its models in T1.1.
    """
    assert list(apps.get_app_config(label).get_models()) == []
