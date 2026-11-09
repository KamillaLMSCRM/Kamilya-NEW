"""Enumerate dictionary agreement possibilities, not syntactic attachments."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_WORD = re.compile(r'[^\W\d_]+', re.UNICODE)
_MODIFIERS = frozenset({'ADJF', 'PRTF'})
_NOMINALS = frozenset({'NOUN', 'NPRO'})
_NOTICE = 'GRAMMATICAL_POSSIBILITIES_NOT_SYNTACTIC_OR_SEMANTIC_TRUTH'


@lru_cache(maxsize=1)
def _analyzer() -> Any:
    import pymorphy3  # type: ignore[import-untyped]

    return pymorphy3.MorphAnalyzer()


def _feature(a: str | None, b: str | None) -> str:
    if a is None or b is None:
        return 'UNKNOWN'
    variants = {'gen1': 'gent', 'gen2': 'gent', 'acc2': 'accs', 'loc1': 'loct', 'loc2': 'loct'}
    a, b = variants.get(a, a), variants.get(b, b)
    return 'COMPATIBLE' if a == b else 'INCOMPATIBLE'


def _agreement(modifier: dict[str, Any], nominal: dict[str, Any]) -> dict[str, str]:
    case = _feature(modifier['case'], nominal['case'])
    number = _feature(modifier['number'], nominal['number'])
    if modifier['number'] == nominal['number'] == 'plur':
        gender = 'NOT_APPLICABLE'
    elif modifier['number'] == nominal['number'] == 'sing':
        gender = _feature(modifier['gender'], nominal['gender'])
    else:
        gender = 'UNKNOWN'
    checks = (case, number, gender)
    status = ('INCOMPATIBLE' if 'INCOMPATIBLE' in checks else
              'UNKNOWN' if 'UNKNOWN' in checks else 'COMPATIBLE')
    return {'case': case, 'number': number, 'gender': gender, 'status': status}


def build_agreement_graph(text: str, spans: list[tuple[int, int]]) -> dict[str, Any]:
    """Analyze explicit nonoverlapping sentence/quote spans with absolute offsets.

    Spans are bounded quotes or paragraphs. Common sentence punctuation and line
    breaks split spans conservatively, including abbreviations and decimal points.
    Offsets are Python Unicode character offsets, start inclusive/end exclusive.
    Omitting text between spans is allowed; boundaries may not split a word.
    """
    if type(text) is not str or not text or type(spans) is not list or not spans:
        raise ValueError('agreement_graph_input_invalid')
    words = list(_WORD.finditer(text))
    previous = 0
    for span in spans:
        if (type(span) not in (tuple, list) or len(span) != 2
                or any(type(x) is not int for x in span)):
            raise ValueError('agreement_graph_span_invalid')
        start, end = span
        if start < previous or start < 0 or end <= start or end > len(text):
            raise ValueError('agreement_graph_span_invalid')
        if any(word.start() < boundary < word.end() for word in words for boundary in (start, end)):
            raise ValueError('agreement_graph_span_splits_word')
        previous = end

    analyzer = _analyzer()
    sections: list[dict[str, Any]] = []
    segments = []
    for start, end in spans:
        segment_start = start
        for index in range(start, end):
            if text[index] in '.!?\r\n':
                segments.append((segment_start, index + 1))
                segment_start = index + 1
        if segment_start < end:
            segments.append((segment_start, end))
    for start, end in segments:
        tokens: list[dict[str, Any]] = []
        for match in words:
            if match.start() < start or match.end() > end:
                continue
            readings = []
            for parse in analyzer.parse(match.group()):
                tag = parse.tag
                readings.append({'normal_form': parse.normal_form, 'tag': str(tag),
                                 'pos': tag.POS, 'case': tag.case,
                                 'number': tag.number, 'gender': tag.gender})
            tokens.append({'text': match.group(), 'start': match.start(), 'end': match.end(),
                           'parses': readings})
        edges: list[dict[str, Any]] = []
        for mi, modifier in enumerate(tokens):
            for ni, nominal in enumerate(tokens):
                if mi == ni:
                    continue
                for mp, m in enumerate(modifier['parses']):
                    if m['pos'] not in _MODIFIERS:
                        continue
                    for np, n in enumerate(nominal['parses']):
                        if n['pos'] in _NOMINALS:
                            edges.append({'modifier_token': mi, 'modifier_parse': mp,
                                          'nominal_token': ni, 'nominal_parse': np,
                                          **_agreement(m, n)})
        sections.append({'start': start, 'end': end, 'tokens': tokens, 'edges': edges})
    return {'notice': _NOTICE, 'semantic_acceptance': False, 'spans': sections}
