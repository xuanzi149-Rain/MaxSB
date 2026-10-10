"""Isolated smoke runtime: discard background bookkeeping messages, no shared Celery queue."""
from maxkb.settings import *  # noqa: F403
CELERY_BROKER_URL = 'memory://'
