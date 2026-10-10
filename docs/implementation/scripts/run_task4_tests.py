"""Run database tests in a disposable database; never migrate the service database."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
os.environ.setdefault('SERVER_NAME', 'web')
import django
from django.conf import settings  # noqa: E402
# Bypass alias-keyed pooling so test setup cannot reuse a service connection.
settings.DATABASES['default']['ENGINE'] = 'django.db.backends.postgresql'
django.setup()
from django.test.utils import get_runner  # noqa: E402
settings.DATABASES['default']['TEST']['NAME'] = 'test_maxsb_memory_task4'
from django.db import connection  # noqa: E402
import psycopg  # noqa: E402
original_create = connection.creation._create_test_db

def create_test_database(*args, **kwargs):
    name = original_create(*args, **kwargs)
    params = connection.get_connection_params()
    params['dbname'] = 'test_maxsb_memory_task4'
    with psycopg.connect(**params, autocommit=True) as test_connection:
        test_connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
    return name

connection.creation._create_test_db = create_test_database
runner = get_runner(settings)(verbosity=2, interactive=False)
try:
    failures = runner.run_tests(sys.argv[1:] or ['application'])
except Exception:
    import traceback
    traceback.print_exc()
    failures = 1
sys.stdout.flush()
sys.stderr.flush()
# All runner teardowns completed; avoid known dependency shutdown hang.
os._exit(int(bool(failures)))
