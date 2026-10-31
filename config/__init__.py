"""PGC project package.

Implements: docs/especificacao/07_arquitetura.md – components.
Exposes the Celery application so that ``@shared_task`` binds to it.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
