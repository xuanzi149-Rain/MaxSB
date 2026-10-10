# coding=utf-8
"""Opt-in dialogue controls; keep raw facts and answers, remove only verified duplicate evidence."""
from copy import deepcopy

from application.retrieval.policy import FOLLOWUP, classify_question


def response_guidance(question, enabled=False):
    if enabled and isinstance(question, str) and classify_question(question)[0] == 'none':
        return ('本轮用户仅寒暄或说明会话安排。只用一句简短中文回应，不复述业务资料、不主动展开建议。'
                '不要声称已完成操作或已持久化记忆；不改变用户此前的业务条件。')
    return ''


def prepare_history(turns, current_context, current_question, enabled=False):
    """Inputs have explicit context provenance; never infer evidence boundaries from prompt syntax."""
    result = deepcopy(turns)
    trace = {'enabled': enabled, 'removed_contexts': 0, 'removed_chars': 0,
             'status': 'disabled' if not enabled else 'preserved'}
    if not enabled or not isinstance(current_question, str) or FOLLOWUP.search(current_question.strip()):
        return result, trace
    if not isinstance(current_context, str) or not current_context.strip():
        return result, trace
    for turn in result:
        context, prompt, raw = turn.get('context'), turn.get('question'), turn.get('raw_question')
        if (isinstance(context, str) and len(context) >= 20 and context == current_context
                and isinstance(prompt, str) and prompt.count(context) == 1
                and isinstance(raw, str) and raw and raw in prompt and raw not in context):
            turn['question'] = prompt.replace(context, '', 1)
            trace['removed_contexts'] += 1
            trace['removed_chars'] += len(context)
    if trace['removed_contexts']:
        trace['status'] = 'duplicate_evidence_removed'
    return result, trace


def dialogue_guidance(question, enabled=False):
    if not enabled:
        return ''
    return ('结合历史中用户明确陈述的业务条件回答；更正以最新原话为准，不把助手推测当作用户事实。'
            + response_guidance(question, True))
