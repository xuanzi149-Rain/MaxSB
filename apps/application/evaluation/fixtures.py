# coding=utf-8
"""Explicit synthetic readonly lookup, executed by the unchanged MaxKB tool node."""
import json
import re
from pathlib import Path

LOOKUP_CODE = '''def lookup(tracking_id: str):
    if tracking_id in ('DEV-TIMEOUT', 'FT01', 'FT02', 'FT03', 'FT04'):
        raise TimeoutError('TASK1_READONLY_TIMEOUT')
    states = {'DEV001': '已揽收', 'DEV002': '待揽收', 'F001': '已揽收', 'F002': '待揽收',
              'F003': '运输中', 'F004': '待领取', 'F005': '已退回', 'F006': '已签收',
              'F007': '拦截中', 'F008': '查无记录'}
    return {'tracking_id': tracking_id, 'status': states.get(tracking_id, '查无记录'),
            'read_only': True, 'outcome': 'success'}
'''


def tool_workflow(tracking_id):
    template = json.loads((Path(__file__).resolve().parents[1] / 'flow/default_workflow.json').read_text())
    nodes = [n for n in template['nodes'] if n['type'] in ('base-node', 'start-node')]
    nodes.append({'id': 'evaluation-lookup', 'type': 'tool-node', 'x': 1150, 'y': 450,
                  'properties': {'stepName': '评测只读查件夹具', 'showNode': True,
                    'config': {'fields': [{'label': '结果', 'value': 'result'}]},
                    'node_data': {'input_field_list': [{'name': 'tracking_id', 'type': 'string',
                                      'is_required': True, 'source': 'custom', 'value': tracking_id}],
                                  'code': LOOKUP_CODE, 'is_result': True}}})
    return {'nodes': nodes, 'edges': [{'id': 'evaluation-start-tool', 'type': 'app-edge',
             'sourceNodeId': 'start-node', 'targetNodeId': 'evaluation-lookup',
             'sourceAnchorId': 'start-node_right', 'targetAnchorId': 'evaluation-lookup_left',
             'startPoint': {'x': 860, 'y': 450}, 'endPoint': {'x': 990, 'y': 450},
             'pointsList': [{'x': 860, 'y': 450}, {'x': 900, 'y': 450},
                            {'x': 950, 'y': 450}, {'x': 990, 'y': 450}], 'properties': {}}]}


def tracking_id_from_question(question):
    ids = re.findall(r'(?<![A-Za-z0-9])(?:DEV\d+|DEV-TIMEOUT|F\d{3}|FT\d{2})(?![A-Za-z0-9])', question)
    if len(ids) != 1:
        raise ValueError('invalid_fixture_tracking_id')
    return ids[0]
