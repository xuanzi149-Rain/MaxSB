"""Compare three exported evaluation runs without issuing paid model requests."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'apps'))
from application.evaluation.routing import compare_routing  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('low', 'high', 'routing', 'protocol', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    if protocol.get('status') != 'ready':
        parser.error('Freeze and mark protocol ready before formal comparison')
    from application.evaluation.dataset import dataset_digest
    groups = {role: json.loads(getattr(args, role).read_text()) for role in ('low', 'high', 'routing')}
    for role, group in groups.items():
        if group.get('status') != 'completed' or group.get('snapshot', {}).get('routing_strategy') != role:
            parser.error('All three exports must be completed and have their declared routing_strategy')
        if group.get('snapshot', {}).get('routing_protocol_hash') != dataset_digest(protocol):
            parser.error('Export protocol does not match the frozen comparison protocol')
        group['contract_hash'] = group.get('config_hash')
    report = compare_routing(groups, protocol)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (args.output / 'inputs.json').write_text(json.dumps(groups, ensure_ascii=False, indent=2))
    print(json.dumps({'comparable': report['comparable'], 'quality_passed': report['quality_passed'],
                      'cost_optimized': report['cost_optimized']}))


if __name__ == '__main__':
    main()
