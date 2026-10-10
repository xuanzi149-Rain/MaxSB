# coding=utf-8
"""No credentials are sent over process arguments or written to result files."""
import json
import logging
from copy import copy
from langchain_core.tracers.context import collect_runs
import re
import sys
from pathlib import Path
import django

django.setup()
from application.models import ChatUserType, Application  # noqa: E402
from application.serializers.common import ChatInfo  # noqa: E402
from chat.serializers.chat import OpenChatSerializers, ChatSerializers  # noqa: E402
from application.evaluation.fixtures import tool_workflow, tracking_id_from_question  # noqa: E402
from application.evaluation.usage import extract_usage  # noqa: E402
from application.evaluation.stream import aggregate_stream  # noqa: E402
from application.evaluation.snapshot import capture_snapshot  # noqa: E402
from common.handle.impl.response.system_to_response import SystemToResponse  # noqa: E402


class FrozenChatInfo(ChatInfo):
    def get_application(self):
        return self.application


def freeze_chat_info(info, snapshot):
    frozen = FrozenChatInfo.__new__(FrozenChatInfo)
    frozen.__dict__.update(info.__dict__)
    frozen.application = copy(Application.objects.get(pk=snapshot['application_id']))
    for key, value in snapshot['application_config'].items():
        setattr(frozen.application, key, value)
    frozen.knowledge_id_list = snapshot['knowledge_ids']
    return frozen


def run_case(case, snapshot):
    identity = {'workspace_id': snapshot['workspace_id'], 'application_id': snapshot['application_id'],
                'chat_user_id': snapshot['user_id'], 'chat_user_type': ChatUserType.PLATFORM_USER, 'debug': True}
    chat_id = OpenChatSerializers(data=identity).open()
    rows, evidence, trace, tool_events = [], set(), [], []
    for question in case['turns']:
        if capture_snapshot(snapshot['application_id'])['config_hash'] != snapshot['config_hash']:
            rows.append({'answer': '', 'complete': False, 'error': 'configuration_drift',
                         'input_tokens': None, 'output_tokens': None})
            break
        serializer = ChatSerializers(data={**identity, 'chat_id': chat_id})
        instance = {'message': question, 'stream': True, 're_chat': False}
        is_tool = case['scenario'] in ('tool_success', 'tool_timeout')
        serializer.is_valid(raise_exception=True)
        info = freeze_chat_info(ChatInfo.get_cache(chat_id), snapshot)
        with collect_runs() as collector:
            if is_tool:
                tracking_ids = [tracking_id_from_question(question)]
                info.application.work_flow = tool_workflow(tracking_ids[0])
                response = serializer.chat_work_flow(info, instance, SystemToResponse())
            elif info.application.type == 'SIMPLE':
                response = serializer.chat_simple(info, instance, SystemToResponse())
            else:
                response = serializer.chat_work_flow(info, instance, SystemToResponse())
            if not getattr(response, 'streaming', False):
                raise ValueError('non_streaming_chat_error')
            try:
                row = aggregate_stream(response.streaming_content)
            finally:
                response.close()
        usage = extract_usage(collector.traced_runs)
        if is_tool:
            usage.update(input_tokens=0, output_tokens=0, usage_source='no_model_called')
        row.update(usage)
        info = ChatInfo.get_cache(chat_id)
        record = ChatSerializers.get_chat_record(info, row['record_id']) if row['record_id'] else None
        if record:
            # Upstream computes these with get_num_tokens; expose as estimates, not billed usage.
            row['estimated_input_tokens'] = record.message_tokens
            row['estimated_output_tokens'] = record.answer_tokens
            for key, node in record.details.items():
                if not isinstance(node, dict):
                    continue
                trace.append({'node_id': key, 'node_type': node.get('step_type', node.get('type')),
                              'status': node.get('status'), 'run_time': node.get('run_time')})
                if is_tool and node.get('type') == 'tool-node':
                    value = node.get('result')
                    if isinstance(value, dict):
                        tool_events.append({k: value[k] for k in ('outcome', 'tracking_id', 'status') if k in value})
                    elif 'TASK1_READONLY_TIMEOUT' in str(node.get('err_message', '')):
                        tool_events.append({'outcome': 'timeout', 'tracking_id': tracking_ids[0]})
                        row['error'] = 'tool_timeout'
                for paragraph in node.get('paragraph_list', []) or []:
                    evidence.update(re.findall(r'\[((?:D|F)-[a-z-]+)\]', paragraph.get('content', '')))
        if capture_snapshot(snapshot['application_id'])['config_hash'] != snapshot['config_hash']:
            row.update(error='configuration_drift', complete=False)
        rows.append(row)
        if row['error'] or not row['complete']:
            break
    answer = rows[-1]['answer'] if rows else ''
    citations = re.findall(r'\[((?:D|F)-[a-z-]+)\]', answer)
    totals = {k: sum(r[k] for r in rows) if rows and all(r.get(k) is not None for r in rows) else None
              for k in ('input_tokens', 'output_tokens')}
    return {'status': 'success' if len(rows) == len(case['turns']) and not any(r['error'] for r in rows) else 'failed',
            'answer': answer, 'turns': rows, 'retrieved_evidence_ids': sorted(evidence), 'citations': citations,
            'trace': trace, **totals, 'actual_cost': None, 'tool_events': tool_events,
            'usage_source': 'see_turns', 'chat_id': chat_id,
            'evaluation_scope': 'controlled_tool_workflow' if case['scenario'].startswith('tool_') else 'application',
            'error': next((r['error'] for r in rows if r['error']), None)}


if __name__ == '__main__':
    # The original engine can log raw provider exceptions. Only structured errors leave this child.
    logging.disable(logging.CRITICAL)
    from application.evaluation.budget import install_budget_guard
    install_budget_guard()
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
        output = run_case(request['case'], request['snapshot'])
    except Exception as exc:
        output = {'status': 'failed', 'answer': '', 'error': type(exc).__name__, 'actual_cost': None}
    Path(sys.argv[2]).write_text(json.dumps(output, ensure_ascii=False))
