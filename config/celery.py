"""Celery application for background jobs (email, SII sync, heavy reports).

Implements: docs/especificacao/07_arquitetura.md – task queue (Celery + Redis).
No tasks are defined yet; this only wires the broker.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("pgc")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
