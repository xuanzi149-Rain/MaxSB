"""Run a named baseline once; requires the normal MaxKB runtime environment and explicit operator invocation."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--application-id', required=True)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--dataset', choices=('dev-v1', 'frozen-v1'), required=True)
    parser.add_argument('--expected-dataset-hash', required=True, help='Hash from the reviewed source checkout')
    parser.add_argument('--label', choices=('dev-a', 'dev-b', 'frozen-baseline'), required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if (args.label == 'frozen-baseline') != (args.dataset == 'frozen-v1'):
        parser.error('Frozen baseline label and dataset must match')
    import django
    django.setup()
    from application.evaluation.dataset import dataset_digest, validate_dataset
    from application.evaluation.service import create_run, execute_run
    from application.models import EvaluationRun
    from django.core.serializers.json import DjangoJSONEncoder
    root = ROOT / 'docs/implementation/evaluation'
    dataset = json.loads((root / (args.dataset + '.json')).read_text())
    corpus = json.loads((root / 'corpus.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    validate_dataset(dataset, corpus)
    if dataset_digest(dataset) != args.expected_dataset_hash:
        raise ValueError('Runtime dataset differs from reviewed checkout')
    if dataset_digest(dataset) != manifest['datasets'][args.dataset] or dataset_digest(corpus) != manifest['corpus_hash']:
        raise ValueError('Sealed input changed')
    if args.dataset == 'frozen-v1' and manifest.get('rubric_review', {}).get('status') != 'reviewed':
        raise ValueError('Rubric review required')
    from application.models import Application
    app = Application.objects.get(pk=args.application_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation survives a crash: never silently replay a baseline label.
    output = args.output_dir / (args.label + '.json')
    with output.open('x') as handle:
        json.dump({'state': 'reserved', 'dataset': args.dataset}, handle)
    run = create_run(app.workspace_id, str(app.pk), args.user_id, dataset, enqueue=False)
    output.write_text(json.dumps({'state': 'started', 'run_id': str(run.pk)}))
    execute_run(str(run.pk))
    run = EvaluationRun.objects.get(pk=run.pk)
    # Import the API exporter only after all child processes exit: its package loads chat/ML dependencies.
    from application.views.evaluation import run_data
    output.write_text(json.dumps(run_data(run, True), cls=DjangoJSONEncoder, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'run_id': str(run.pk), 'status': run.status, 'output': str(output)}))
    if run.status != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
