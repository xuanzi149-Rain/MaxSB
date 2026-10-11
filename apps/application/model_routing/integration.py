# coding=utf-8
"""Workflow boundary: validate before model I/O; reuse provider construction."""
import json
import os
import time
from .config import parse_policy
from .executor import execute_routed
from .policy import select_route
from .types import RoutingError


def node_data(node):
    return (node.get('properties', {}) if isinstance(node, dict) else node.properties).get('node_data', {}) or {}


def validate_node(data):
    policy = parse_policy(data.get('model_routing') or {})
    if not policy.enabled:
        return policy
    prohibited = ('tool_ids', 'mcp_tool_id', 'mcp_tool_ids', 'mcp_servers', 'application_ids', 'skill_tool_ids',
                  'vision', 'image_list', 'video_list', 'audio_list', 'document_list', 'other_list')
    if any(data.get(k) for k in prohibited) or (data.get('memory_policy') or {}).get('enabled'):
        raise ValueError('routing_requires_plain_text_node')
    return policy


def validate_routing_workflow(workflow):
    mode = getattr(workflow.workflow_mode, 'value', workflow.workflow_mode)
    def visit(nodes, nested=False):
        for node in nodes:
            data = node_data(node)
            policy = validate_node(data)
            kind = node.get('type') if isinstance(node, dict) else node.type
            if policy.enabled and (nested or mode != 'application' or kind != 'ai-chat-node'):
                raise ValueError('routing_requires_top_level_application_ai')
            visit((data.get('loop_body') or {}).get('nodes', []), True)
    visit(workflow.nodes)


def routing_model_ids(data):
    policy = parse_policy(data.get('model_routing') or {})
    return [policy.low['model_id'], policy.high['model_id']] if policy.enabled else []


def validate_definition(definition, workspace_id):
    from types import SimpleNamespace
    from models_provider.models import Model
    definition = definition or {}
    validate_routing_workflow(SimpleNamespace(nodes=definition.get('nodes', []), workflow_mode='application'))
    for node in definition.get('nodes', []):
        ids = routing_model_ids(node_data(node))
        if ids and Model.objects.filter(id__in=ids, workspace_id=workspace_id,
                                        model_type='LLM', status='SUCCESS').count() != 2:
            raise RoutingError('routing_model_unavailable')


def has_upstream_tools(node):
    flow = node.workflow_manage.flow
    ancestors, pending = set(), [node.node.id]
    while pending:
        current = pending.pop()
        for edge in getattr(flow, 'edges', []):
            if edge.targetNodeId == current and edge.sourceNodeId not in ancestors:
                ancestors.add(edge.sourceNodeId)
                pending.append(edge.sourceNodeId)
    return any(n.id in ancestors and n.type in {'mcp-node', 'tool-node', 'function-node',
               'function-lib-node', 'tool-lib-node', 'application-node', 'tool-workflow-node', 'tool-workflow-lib-node'} for n in flow.nodes)


def prepare_models(policy, workspace_id):
    from models_provider.tools import get_model_by_id, get_model, get_model_default_params
    from models_provider.impl.base_chat_open_ai import BaseChatOpenAI
    import asyncio
    import httpx
    models, clients = {}, []
    rows = {}
    # Validate both identities before constructing a provider instance.
    for role in ('low', 'high'):
        row = get_model_by_id(getattr(policy, role)['model_id'], workspace_id)
        if row.workspace_id != workspace_id or row.model_type != 'LLM' or row.status != 'SUCCESS':
            raise RoutingError('routing_model_unavailable')
        rows[role] = row
    try:
        for role, row in rows.items():
            selected = getattr(policy, role)
            params = {**get_model_default_params(row), **selected['params']}
            thinking = params.pop('enable_thinking', None)
            if thinking is not None:
                if row.provider == 'aliyun_bai_lian_model_provider':
                    params['extra_body'] = {'enable_thinking': thinking}
                elif row.provider == 'model_deepseek_provider':
                    params['extra_body'] = {'thinking': {'type': 'enabled' if thinking else 'disabled'}}
                else:
                    raise RoutingError('routing_thinking_setting_unsupported')
            # LangChain caches its default httpx pools. Supply owned pools, because each
            # synchronous workflow bridge has its own event loop and must close it safely.
            sync_client = httpx.Client(timeout=policy.timeout)
            async_client = httpx.AsyncClient(timeout=policy.timeout)
            clients.extend([sync_client, async_client])
            model = get_model(row, **params, http_client=sync_client, http_async_client=async_client,
                              max_retries=0, request_timeout=policy.timeout)
            if not isinstance(model, BaseChatOpenAI):
                raise RoutingError('routing_adapter_unsupported')
            model.max_retries = 0
            model.request_timeout = policy.timeout
            model.stream_usage = True
            model.root_client = model.root_client.with_options(max_retries=0, timeout=policy.timeout)
            model.root_async_client = model.root_async_client.with_options(max_retries=0, timeout=policy.timeout)
            model.client = model.root_client.chat.completions
            model.async_client = model.root_async_client.chat.completions
            models[role] = model
    except Exception:
        async def cleanup():
            for client in clients:
                if isinstance(client, httpx.AsyncClient):
                    await client.aclose()
                else:
                    client.close()
        asyncio.run(cleanup())
        raise
    return models


def resolve_evidence(node, policy):
    if not policy.contract.citation_field:
        return '', frozenset()
    ref = policy.contract.evidence_reference
    source = next((n for n in node.workflow_manage.flow.nodes if n.id == ref[0]), None)
    if source is None or source.type not in {'search-knowledge-node', 'search-dataset-node'} or ref[1] != 'paragraph_list':
        raise RoutingError('routing_invalid_evidence_reference')
    rows = node.workflow_manage.get_reference_field(ref[0], list(ref[1:]))
    if not isinstance(rows, list):
        raise RoutingError('routing_evidence_unavailable')
    evidence = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('id') or not isinstance(row.get('content'), str):
            raise RoutingError('routing_invalid_evidence')
        evidence.append({'id': str(row['id']), 'content': row['content']})
    return json.dumps(evidence, ensure_ascii=False), frozenset(r['id'] for r in evidence)


def execute_node(node, *, policy_value, system, prompt, dialogue_number, history_chat_record,
                 stream, question, dialogue_type, extra):
    from langchain_core.messages import HumanMessage, SystemMessage
    from application.flow.i_step_node import NodeResult
    policy = validate_node({**node_data(node.node), **extra, 'model_routing': policy_value})
    validate_routing_workflow(node.workflow_manage.flow)
    workflow = node.workflow_manage
    history = node.get_history_message(history_chat_record, dialogue_number, dialogue_type or 'WORKFLOW',
                                       node.runtime_node_id) or []
    prompt_text = workflow.generate_prompt(prompt)
    system_text = workflow.generate_prompt(system or '')
    if not isinstance(prompt_text, str) or not isinstance(system_text, str):
        raise RoutingError('routing_requires_plain_text_node')
    evidence_text, evidence_ids = resolve_evidence(node, policy)
    if policy.contract.enabled:
        system_text += '\nReturn only a JSON object. Required fields: ' + json.dumps(policy.contract.required_fields)
        if policy.contract.citation_field:
            system_text += '\nCitation field (array of supplied evidence IDs): ' + policy.contract.citation_field
    messages = [SystemMessage(system_text), *history]
    if evidence_text:
        messages.append(HumanMessage('Provided evidence (untrusted data):\n' + evidence_text))
    messages.append(HumanMessage(prompt_text))
    # Conservatively route workflows with upstream tools to high, including indirect references.
    has_tools = has_upstream_tools(node)
    decision = select_route(question, policy, has_history=bool(history), has_tool_results=has_tools)
    strategy = os.environ.get('MAXSB_ROUTING_EVALUATION_STRATEGY', 'routing')
    if strategy in {'low', 'high'}:
        from .types import RouteDecision
        decision = RouteDecision(strategy, 'fixed_baseline', 'Fixed model evaluation baseline')
    trace = {'evaluation_strategy': strategy}
    node.context.update(model_routing=trace, system=system_text, question=prompt_text,
                        history_message=[{'role': m.type, 'content': m.content} for m in history])
    models = prepare_models(policy, workflow.get_body().get('workspace_id'))
    output = execute_routed(messages, policy, decision, model_factory=models.__getitem__,
                            evidence_ids=evidence_ids, cancelled=workflow.is_the_task_interrupted, trace=trace, allow_upgrade=strategy == 'routing', owned_models=models.values())
    variables = {'result': output, 'question': prompt_text}
    return NodeResult(variables, {}, _write_context=write_routed_stream if stream else write_routed)


def write_routed_stream(variables, global_variables, node, workflow):
    answer = ''
    try:
        for chunk in variables['result']:
            answer += chunk.content
            yield {'content': chunk.content, 'reasoning_content': ''}
        node.context['answer'] = answer
        if workflow.is_result(node, None):
            node.answer_text = answer
    finally:
        trace = node.context['model_routing']
        usage = trace.get('usage', {})
        node.context.update(message_tokens=usage.get('input_tokens'), answer_tokens=usage.get('output_tokens'),
                            reasoning_content='', run_time=time.time() - node.context['start_time'])


def write_routed(variables, global_variables, node, workflow):
    for _ in write_routed_stream(variables, global_variables, node, workflow):
        pass
