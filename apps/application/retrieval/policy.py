# coding=utf-8
"""Deterministic retrieval budgets. Unknown questions preserve the fixed configuration."""
import re
import unicodedata


DEFAULT_PROFILES = {
    'none': {'retrieve': False, 'top_n': 1, 'rerank': False},
    'simple': {'retrieve': True, 'top_n': 3, 'rerank': False},
    'complex': {'retrieve': True, 'top_n': 8, 'rerank': True},
}
GREETINGS = {'你好', '您好', '嗨', '哈喽', '谢谢', '多谢', '再见', 'hello', 'hi', 'thanks', 'thank you', 'bye'}
COMPARISON = re.compile(r'比较|对比|区别|差异|优缺点|同时|并且|而且|以及|且|分别|compare|difference|versus|\bvs\b',
                        re.I)
FACT = re.compile(r'多少|几[天本人次个元岁]|多久|何时|哪里|哪年|是谁|是什么|是否|能否|可以.{0,12}吗|'
                  r'\b(?:what is|who is|when|where|how many|how much|how long)\b', re.I)
FOLLOWUP = re.compile(r'上述|上面|上文|刚才|之前|前面|前者|后者|那条|这条|它|他们|她|他|这个|那个|'
                      r'这项|那项|第二个|这次|本次|\b(?:it|that|this)\b', re.I)


# Full matches only: a business question/correction appended to a control must never skip retrieval.
SESSION_CONTROL = re.compile(
    r'(?:请)?(?:先|暂时)?(?:记住|保留)(?:前面|之前|刚才)的(?:要求|信息|条件)'
    r'|(?:请)?(?:先|暂时)?(?:不要|不需要|不)(?:执行任何操作|执行|制定计划)'
    r'|(?:请)?(?:用|使用)(?:简短条目|简短文字|简洁语言)(?:回答|回复|答复)'
    r'|(?:请)?(?:简短|简洁)(?:回答|回复|答复)'
    r'|我(?:希望|偏好|更喜欢)(?:用|使用)(?:简短条目|简短文字|简洁语言)(?:回答|回复|答复)')
SIDE_NOTE = re.compile(r'补充一个无关安排[：:]我(?:今天|今晚|晚上|下午|晚饭后)?(?:准备|要|会|打算)?'
                       r'(?:浇花|画画|整理书桌|散步|清理电子邮件)[，,]这不改变之前的条件')
COMPOUND = re.compile(r'及|与|和|、|[;；]|\band\b', re.I)
NUMERIC_OR_CALCULATION = re.compile(r'\d|[零〇一二两三四五六七八九十百千万半]|'
                                    r'计算|计费|折后|合计|总价|体积|限重|预算')


def classify_question(question):
    text = unicodedata.normalize('NFKC', question).strip().lower()
    if text.strip(' !?。，,.；;') in GREETINGS:
        return 'none', 'exact_greeting'
    control = text.strip(' !?。，,.；;')
    clauses = re.split(r'[，,。；;]', control)
    if clauses and all(SESSION_CONTROL.fullmatch(clause.strip()) for clause in clauses):
        return 'none', 'conversation_control'
    if (SIDE_NOTE.fullmatch(control) and not FACT.search(control)
            and not re.search(r'\d|改为|更正|取消|订单|预算|运费|寄件|借阅', control)):
        return 'none', 'explicit_side_note'
    if not text or FOLLOWUP.search(text):
        return 'unknown', 'ambiguous_or_followup'
    if COMPARISON.search(text) or len(FACT.findall(text)) > 1 or len(re.findall(r'[?？]', text)) > 1:
        return 'complex', 'comparison_or_multiple_conditions'
    if COMPOUND.search(text) and FACT.search(text):
        return 'complex', 'multiple_requirements'
    if NUMERIC_OR_CALCULATION.search(text):
        return 'unknown', 'numeric_or_calculation_requires_evidence'
    # Extra clauses are not proven single-fact requests; only strip a standalone greeting.
    fact_text = re.sub(r'^(?:你好|您好|hello|hi)[，,]\s*', '', text)
    if re.search(r'[，,。;；\n]', fact_text.rstrip('。')):
        return 'unknown', 'additional_clause'
    # A single bounded fact question; long or compound requests conservatively fall back.
    if len(text) <= 100 and FACT.search(text) and not re.search(r'[;；]|\band\b|和|与', text):
        return 'simple', 'single_fact'
    return 'unknown', 'no_explicit_rule'


def decide_retrieval(question, settings):
    policy = settings.get('retrieval_policy') or {}
    if not policy.get('enabled', False):
        return None
    category, reason = classify_question(question)
    profile = {'retrieve': True, 'top_n': settings['top_n'], 'rerank': None}
    if category in DEFAULT_PROFILES:
        profile = {**DEFAULT_PROFILES[category], **policy.get(category, {})}
    if not profile['retrieve']:
        profile = {**profile, 'top_n': 0, 'rerank': False}
    return {'version': 2, 'question': question, 'category': category, 'reason': reason, **profile,
            'similarity': settings['similarity'], 'search_mode': settings['search_mode']}
