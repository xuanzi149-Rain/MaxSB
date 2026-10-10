import faulthandler
import os
import sys
faulthandler.enable()
faulthandler.dump_traceback_later(120, repeat=True)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
import django
django.setup()
from django.conf import settings
from django.test.utils import get_runner
runner = get_runner(settings)(verbosity=2)
failures = runner.run_tests(sys.argv[1:] or ['application'])
faulthandler.cancel_dump_traceback_later()
sys.stdout.flush()
sys.stderr.flush()
# Test runner has finished all teardowns. Avoid third-party interpreter-shutdown hangs.
os._exit(int(bool(failures)))
