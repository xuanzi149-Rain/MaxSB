# coding=utf-8
"""Only explicit single operations qualify for the cheaper model."""
import re
from .types import RouteDecision

COMPLEX = re.compile(r'比较|对比|综合|分析|解释|原因|推理|分别|并且|以及|同时|然后|但是|还要|并|；|;|\n|'
                     r'\b(compare|contrast|analy[sz]e|explain|reason|and|then|also|but)\b', re.I)
SIMPLE = re.compile(r'^(?:请|仅|只|只需|请仅|请只)?\s*(?:提取|抽取|分类)|^(?:please\s+)?(?:extract|classify)\b', re.I)


def select_route(question, policy, *, has_history, has_tool_results):
    if has_tool_results:
        return RouteDecision('high', 'tool_results', 'Upstream tool results require synthesis')
    if has_history:
        return RouteDecision('high', 'history', 'History-dependent task')
    if not policy.contract.enabled:
        return RouteDecision('high', 'no_contract', 'No machine-verifiable output contract')
    if not isinstance(question, str) or not question.strip() or len(question) > 512 or COMPLEX.search(question):
        return RouteDecision('high', 'complex_or_unknown', 'Complex, mixed or unknown task')
    if SIMPLE.search(question.strip()):
        return RouteDecision('low', 'simple_structured', 'Explicit extraction or classification with output contract')
    return RouteDecision('high', 'unknown', 'Unrecognized task')
