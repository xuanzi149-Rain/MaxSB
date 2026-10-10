"""Settings for the disposable 8084 release and its evaluation children."""
from pathlib import Path

from maxkb.settings import *  # noqa: F403

assert CONFIG.get('DB_NAME') == 'maxsb_task4_staging'  # noqa: F405
assert str(CONFIG.get('REDIS_DB')) == '14'  # noqa: F405
DATABASES['default'].update(ENGINE='django.db.backends.postgresql', NAME='maxsb_task4_staging')  # noqa: F405
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'closure-stage'}}
SECRET_KEY = Path('/tmp/maxsb-closure-staging/.staging-secret').read_text()
DEBUG = False
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
