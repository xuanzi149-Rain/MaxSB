"""Prepare labeled A/B answers for a real human; never assigns human scores."""
import argparse
import html
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cases', type=Path, required=True)
parser.add_argument('--records', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
cases = json.loads(args.cases.read_text())
records = json.loads(args.records.read_text())
rows, mapping = [], []
for number, case in enumerate(cases, 1):
    order = ('memory', 'fixed') if number % 2 else ('fixed', 'memory')
    answers = []
    for label, strategy in zip('AB', order):
        matches = [r for r in records if r['case_id'] == case['id'] and r['strategy'] == strategy]
        assert len(matches) == len(case['turns']), 'Incomplete evaluation'
        answer = matches[-1].get('answer') or ('ERROR: ' + matches[-1].get('error', 'missing'))
        answers.append(f'<div><h3>{label}</h3><p>{html.escape(answer)}</p></div>')
        mapping.append({'question': number, 'case_id': case['id'], 'label': label, 'strategy': strategy,
                        'human_score': None})
    rows.append(f'<section><h2>{number}. {html.escape(case["id"])}</h2>'
                f'<p><b>验收要求：</b>{html.escape(case["expected"])}</p>'
                f'<details><summary>完整输入与清空位置</summary><pre>{html.escape(json.dumps(case, ensure_ascii=False, indent=2))}</pre></details>'
                f'<div class="answers">{"".join(answers)}</div></section>')
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text('''<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>任务4人工质量复核</title><style>body{max-width:1050px;margin:32px auto;padding:0 20px;font:17px/1.7 system-ui;color:#17212b;background:#f6f8fa}section{background:white;border:1px solid #ddd;border-radius:12px;padding:20px;margin:20px 0}h1{font-size:28px}h2{font-size:21px}.answers{display:grid;grid-template-columns:1fr 1fr;gap:20px}.answers>div{background:#f3f7fa;padding:12px;border-radius:8px}p,pre{white-space:pre-wrap;overflow-wrap:anywhere}pre{font-size:14px}@media(max-width:600px){.answers{grid-template-columns:1fr}}</style>
<h1>任务4 · 人工质量复核</h1><p>以下是同一模型、相同对话的两种策略，A/B顺序逐题轮换。请按每题要求判定哪份答案符合；允许两份都符合或都不符合。请在聊天中回复，例如“1A，2B，3都不符合”，并说明不符合原因。这里只提供原始答案，不自动写入人工评分。</p>
''' + ''.join(rows) + '</html>')
args.output.with_suffix('.mapping.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
