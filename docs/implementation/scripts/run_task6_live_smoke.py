"""Read-only model lookup plus bounded paid routing smoke; no application/DB writes."""
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'task6_live_settings')
os.environ['SERVER_NAME'] = 'web'
import django  # noqa: E402
django.setup()
from application.evaluation.budget import install_budget_guard  # noqa: E402
from application.model_routing.config import parse_policy  # noqa: E402
from application.model_routing.integration import prepare_models  # noqa: E402
from application.model_routing.policy import select_route  # noqa: E402
from application.model_routing.executor import execute_routed  # noqa: E402
from application.model_routing.types import RouteDecision  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=False)
    allowance = {'version': 2, 'limit_cny': '100', 'reserved_cny': '0', 'requests': 0, 'models': {
        'qwen3.7-plus': {'endpoint': 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions',
                        'input_per_million': '20', 'output_per_million': '80', 'max_tokens': 1024},
        'deepseek-v4-flash': {'endpoint': 'https://api.deepseek.com/chat/completions',
                             'input_per_million': '20', 'output_per_million': '80', 'max_tokens': 1024}}}
    budget = Path(sys.argv[2]) if len(sys.argv) > 2 else output / 'budget.json'
    if not budget.exists():
        budget.write_text(json.dumps(allowance))
    protocol = json.loads((ROOT / 'docs/implementation/evaluation/task6-protocol.json').read_text())
    os.environ['MAXSB_EVALUATION_BUDGET_FILE'] = str(budget)
    install_budget_guard()
    policy = parse_policy({'enabled': True,
        'low': {'model_id': '01a11e76-45ee-79c1-bf92-2bb8dd5a9c42',
                'params': {'temperature': 0, 'max_tokens': 1024, 'enable_thinking': False}},
        'high': {'model_id': '01a11f05-0114-7e73-859e-5cc08ccb3e70',
                 'params': {'temperature': 0, 'max_tokens': 1024, 'enable_thinking': False}},
        'contract': {'required_fields': ['answer']}, 'timeout': 60})
    cases = [('extract', '提取以下信息中的姓名：姓名李明，年龄25岁。'),
             ('classify', '分类这个评价为正面或负面：服务很好，下次还来。'),
             ('compare', '比较方案A（每月20元、10GB）与B（每月30元、30GB）的流量单价。'),
             ('unknown', '为什么要给实验保留失败记录？'),
             ('mixed', '提取借期并解释续借条件：借期21天，可续借14天，但预约中的书不可续借。'),
             ('evidence', '综合资料：规则一借期21天；规则二儿童限借3本。请回答儿童可借几本、多久。')]
    run_id = str(uuid4())
    for role in ('low', 'high', 'routing'):
        for case_id, question in cases:
            models = prepare_models(policy, 'default')
            decision = (select_route(question, policy, has_history=False, has_tool_results=False)
                        if role == 'routing' else RouteDecision(role, 'fixed_baseline', 'Fixed baseline'))
            trace, answer = {}, ''
            started = time.monotonic()
            try:
                for chunk in execute_routed([SystemMessage('请仅输出JSON对象，必须包含answer字段，简洁回答。'),
                    HumanMessage(question)], policy, decision, model_factory=models.__getitem__,
                    evidence_ids=frozenset(), cancelled=lambda: False, trace=trace, allow_upgrade=role == 'routing', owned_models=models.values()):
                    answer += chunk.content
                status = 'success'
            except Exception as exc:
                status = 'failed'
                trace.setdefault('error', type(exc).__name__)
            from application.evaluation.routing import price_trace
            price_trace(trace, protocol.get('prices', {}))
            row = {'run_id': run_id, 'group': role, 'case_id': case_id, 'question': question, 'answer': answer,
                   'status': status, 'elapsed_seconds': time.monotonic()-started, 'model_routing': trace,
                   'actual_cost': None, 'scope': 'six_new_development_smoke_cases_not_frozen_acceptance'}
            (output / f'{role}-{case_id}.json').write_text(json.dumps(row, ensure_ascii=False, indent=2))
            print(role, case_id, status, flush=True)
            # Stop on provider/credential/budget errors; preserve all diagnostics, never burn the remaining allowance.
            if status == 'failed' and trace.get('error') not in {'invalid_json', 'missing_fields'}:
                return 1
    return 0


if __name__ == '__main__':
    result = main()
    sys.stdout.flush()
    os._exit(result)
