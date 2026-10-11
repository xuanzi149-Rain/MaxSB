"""Fixed local acceptance DB; inherited by evaluation subprocesses before Django starts."""
import os
import json
from copy import deepcopy
from pathlib import Path
from maxkb.settings import *  # noqa: F403
from maxkb.settings import DATABASES
from maxkb import settings as base_settings

ROOT = Path('/tmp/maxsb-task6-staging')
SOURCE_DATABASE = deepcopy(DATABASES['default'])
DATABASES['default'].update(ENGINE='django.db.backends.postgresql', NAME='maxsb_task4_staging')
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'task6-stage'}}
SECRET_KEY = (ROOT / '.staging-secret').read_text()
DEBUG = False
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_IGNORE_RESULT = True
for key in ('CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND', 'CELERY_TASK_ALWAYS_EAGER', 'CELERY_TASK_IGNORE_RESULT'):
    setattr(base_settings, key, globals()[key])
os.environ.setdefault('MAXSB_EVALUATION_BUDGET_FILE', '/tmp/task6-live-smoke-01/budget.json')
release = json.loads((ROOT / 'release.json').read_text())
os.environ.setdefault('MAXSB_CODE_SHA', release['code_sha'])
os.environ.setdefault('MAXSB_LOCAL_DIFF_HASH', release['local_diff_hash'])
os.environ.setdefault('MAXSB_IMAGE_ID', release['image_id'])
