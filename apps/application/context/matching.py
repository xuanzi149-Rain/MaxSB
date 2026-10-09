# coding=utf-8
"""Comparison-only normalization. Original evidence is never rewritten."""
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser

# Width folding only: general NFKC would also turn x² into x2.
WIDTH = str.maketrans({**{chr(i): chr(i - 0xFEE0) for i in range(0xFF01, 0xFF5F)}, '\u3000': ' '})
SOURCE_LABEL = re.compile(r'^\s*\[(?:D|F)-[a-z-]+\]\s*')
# A deliberately closed grammar of independent numeric properties, not general
# natural-language entailment. Unknown properties/units/scope fall back to keep.
FACT_UNITS = {
    '借阅上限': {'本'}, '借期': {'天'}, '容量': {'人', '件', '升'},
    '数量上限': {'本', '件', '个'}, '重量上限': {'克', '千克'},
    '长度上限': {'厘米', '米'}, '宽度上限': {'厘米', '米'},
    '高度上限': {'厘米', '米'}, '时长上限': {'分钟', '小时', '天'},
}
FACT = re.compile(r'([\u4e00-\u9fffA-Za-z0-9]{2,40})的([^的]+)为(\d+(?:\.\d+)?)([\u4e00-\u9fff]+)')
SCOPE_WORD = re.compile(r'不|无|非|仅|只|若|如果|当|否则|必须|以上|上述|下述|该|其|此|'
                        r'作废|更正|修订|变更|取代|替代|例外|适用|有效|截至|截止|示例|错误|假设|引用')


def sensitive_structure(text):
    return bool(re.search(r'[`|]|\[[^\]]*\]\(', text))


class PlainFormatting(HTMLParser):
    """Only remove a small allowlist of formatting tags without attributes."""
    blocks = {'p', 'div', 'li', 'ul', 'ol', 'br'}
    inline = {'strong', 'b', 'em', 'i', 'span'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.safe = True
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.blocks | self.inline or attrs:
            self.safe = False
        if tag != 'br':
            self.stack.append(tag)
        if tag in self.blocks:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.safe = False
        if tag in self.blocks:
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_comment(self, data):
        self.safe = False

    def handle_decl(self, decl):
        self.safe = False

    def handle_pi(self, data):
        self.safe = False

    def unknown_decl(self, data):
        self.safe = False


def normalize(text):
    return ' '.join((text or '').split())


def comparison_text(text, *, source_label=False):
    text = text or ''
    original = text
    if sensitive_structure(text):
        return text
    text = text.translate(WIDTH)
    if source_label:
        text = SOURCE_LABEL.sub('', text, count=1)
    if '<' in text or '&' in text:
        parser = PlainFormatting()
        parser.feed(text)
        parser.close()
        if parser.safe and not parser.stack:
            text = ''.join(parser.parts)
        else:
            return original
    # Only unnumbered bullets: numbers may themselves be meaningful evidence.
    text = re.sub(r'(?m)^\s*(?:•\s+|[-*+]\s+(?=[\u4e00-\u9fff]))', '', text)
    text = re.sub(r'\*\*([^*\n]+)\*\*', r'\1', text)
    return normalize(text)


def equivalence_key(text):
    # Punctuation may encode lists, scopes and numbers. Only a trailing sentence
    # delimiter can differ; width variants were already folded explicitly.
    return tuple(re.findall(r'\d+(?:[.,]\d+)*|[A-Za-z_]+|[^\s]', text.rstrip('。.;；')))


def duplicate_kind(a, b, threshold):
    if a == b:
        return 'duplicate'
    if sensitive_structure(a) or sensitive_structure(b) or '<' in a or '<' in b:
        return None
    if equivalence_key(a) == equivalence_key(b) and SequenceMatcher(None, a, b, autojunk=False).ratio() >= threshold:
        return 'near_duplicate'
    return None


def clauses(text):
    """Parse only explicit same-subject numeric facts with known independent units.

    Free prose, qualifications, multiple subjects and conflicting property values
    are never inferred to be redundant. End of paragraph is a clause boundary.
    """
    if SCOPE_WORD.search(text):
        return ()
    facts = []
    subject = None
    properties = set()
    for part in re.split(r'[。；;]|(?<!\d)\.(?!\d)', text):
        if not part.strip():
            continue
        match = FACT.fullmatch(part.strip())
        if not match:
            return ()
        entity, attribute, value, unit = match.groups()
        if unit not in FACT_UNITS.get(attribute, ()) or attribute in properties:
            return ()
        if subject is not None and entity != subject:
            return ()
        subject = entity
        properties.add(attribute)
        facts.append((entity, attribute, value, unit))
    return tuple(facts)


def contains(container, contained):
    """Strict contiguous sequence of typed independent facts; not similarity."""
    if not container or not contained or len(container) <= len(contained):
        return False
    return any(container[i:i + len(contained)] == contained for i in range(len(container) - len(contained) + 1))
