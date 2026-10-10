"""Disposable routing tests: no business database, cache or queue."""
from maxkb.settings import *  # noqa: F403
from maxkb.settings import DATABASES
from maxkb import settings as base_settings
DATABASES['default'].update(ENGINE='django.db.backends.postgresql', NAME='postgres',
                            USER='postgres', PASSWORD='', HOST='127.0.0.1', PORT=5432)
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

# The upstream Celery app imports maxkb.settings directly.
base_settings.CELERY_BROKER_URL = CELERY_BROKER_URL
base_settings.CELERY_RESULT_BACKEND = CELERY_RESULT_BACKEND
