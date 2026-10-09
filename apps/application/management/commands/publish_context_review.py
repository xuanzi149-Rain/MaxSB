# coding=utf-8
"""Install an explicitly reviewed offline cache snapshot; never call a model."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from contextlib import closing

from django.core.management.base import BaseCommand, CommandError
from application.context.runtime import model_revision
from application.context.semantic import digest


class Command(BaseCommand):
    help = 'Publish trusted operator-reviewed semantic pairs into the online read-only registry.'

    def add_arguments(self, parser):
        parser.add_argument('--review', required=True, type=Path)
        parser.add_argument('--cache', required=True, type=Path)
        parser.add_argument('--workspace', required=True)
        parser.add_argument('--output', type=Path,
                            default=Path(os.environ.get('MAXKB_SEMANTIC_REGISTRY',
                                                        '/opt/maxkb/conf/semantic-context.json')))

    def handle(self, *args, **options):
        try:
            review = json.loads(options['review'].read_text())
            workspace = options['workspace']
            if review['namespace'] != workspace + '/reviewed-context':
                raise ValueError('review namespace must match online workspace')
            if not review.get('authorization') or not 1 <= len(review['approvals']) <= 100:
                raise ValueError('explicit reviewed approvals required')
            if not all(review['versions'].get(k) for k in ('judge', 'embedding')):
                raise ValueError('versioned judgement required')
            if not 1 <= len(review['model_bindings']) <= 4 or any(
                    model_revision(b['id'], workspace) != b['revision'] for b in review['model_bindings']):
                raise ValueError('model revision mismatch')
            entries = {}
            with closing(sqlite3.connect(options['cache'].resolve().as_uri() + '?mode=ro', uri=True)) as db:
                for key, fingerprint in review['approvals'].items():
                    row = db.execute('SELECT value, created FROM pairs WHERE key=?', (key,)).fetchone()
                    if row is None or not 0 <= time.time() - row[1] < 86400:
                        raise ValueError('missing or expired reviewed pair')
                    value = json.loads(row[0])
                    if digest(value) != fingerprint:
                        raise ValueError('reviewed judgement changed')
                    entries[key] = {'value': value, 'created': row[1]}
            output = options['output']
            registry = json.loads(output.read_text()) if output.exists() else {'schema': 1, 'scopes': {}}
            if registry['schema'] != 1:
                raise ValueError('unsupported registry schema')
            registry['scopes'][workspace] = {k: review[k] for k in
                                             ('namespace', 'versions', 'model_bindings', 'approvals')}
            registry['scopes'][workspace]['entries'] = entries
            raw = json.dumps(registry, ensure_ascii=False).encode()
            if len(raw) > 2_000_000:
                raise ValueError('registry exceeds runtime size limit')
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
            try:
                os.replace(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)
        except (KeyError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
            raise CommandError('Registry not published: ' + type(exc).__name__) from None
        self.stdout.write(f'Published {len(entries)} reviewed pairs for workspace {workspace}; no model calls.')
