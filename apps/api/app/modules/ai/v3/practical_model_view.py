"""Request-local source aliases; canonical source identities remain authoritative."""
from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _validate_packet


@dataclass(frozen=True, slots=True, init=False)
class PracticalModelView:
    canonical_to_alias: Mapping[str, str]
    alias_to_canonical: Mapping[str, str]

    def __init__(self, packet: PracticalSourcePacket) -> None:
        _validate_packet(packet)
        ids = [block.block_id for block in packet.blocks if block.text.strip()]
        forward = {source: f'SRC{index}' for index, source in enumerate(ids, 1)}
        object.__setattr__(self, 'canonical_to_alias', MappingProxyType(forward))
        object.__setattr__(self, 'alias_to_canonical', MappingProxyType({v: k for k, v in forward.items()}))

    def schema(self, fmt: Any) -> Any:
        result = copy.deepcopy(fmt)
        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == 'enum' and isinstance(value, list):
                        node[key] = [self.canonical_to_alias.get(item, item) if isinstance(item, str) else item
                                     for item in value]
                    else:
                        walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(result)
        return result

    def _convert(self, value: Any, mapping: Mapping[str, str]) -> Any:
        result = copy.deepcopy(value)
        def refs(items: Any) -> list[str]:
            if not isinstance(items, list) or any(type(item) is not str or item not in mapping for item in items):
                raise ValueError('practical_model_source_ref_invalid')
            return [mapping[item] for item in items]
        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if 'source_refs' in node:
                    node['source_refs'] = refs(node['source_refs'])
                for basis in ('narrative_sources', 'question_sources'):
                    if basis in node:
                        narrative = node[basis]
                        if not isinstance(narrative, dict):
                            raise ValueError('practical_model_source_ref_invalid')
                        node[basis] = {key: refs(value) for key, value in narrative.items()}
                if type(node.get('scope')) is str and node['scope'] in {'source', 'coverage'}:
                    for key in ('target_id', 'id'):
                        if key not in node:
                            continue
                        target = node[key]
                        if (type(target) is not str or target not in mapping and (
                                node['scope'] == 'source' or re.fullmatch(r'SRC[1-9]\d*', target)
                                or target.startswith('src-'))):
                            raise ValueError('practical_model_source_ref_invalid')
                        # Coverage can refer to an existing lesson. Its closed inventory is
                        # checked by the review contract, rather than guessed by this codec.
                        node[key] = mapping.get(target, target)
                for key, child in node.items():
                    if key not in {'source_refs', 'narrative_sources', 'question_sources', 'target_id'}:
                        walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(result)
        return result

    def encode(self, value: Any) -> Any:
        return self._convert(value, self.canonical_to_alias)

    def decode(self, value: Any) -> Any:
        return self._convert(value, self.alias_to_canonical)

    def assert_course_ids_disjoint(self, course: dict[str, Any]) -> None:
        if not isinstance(course, dict) or not isinstance(course.get('lessons'), list):
            raise ValueError('practical_model_course_invalid')
        for lesson in course['lessons']:
            if not isinstance(lesson, dict) or not isinstance(lesson.get('questions'), list):
                raise ValueError('practical_model_course_invalid')
            ids = [lesson.get('id'), *(q.get('id') if isinstance(q, dict) else None for q in lesson['questions'])]
            if any(type(item) is not str or not item or re.fullmatch(r'SRC[1-9]\d*', item)
                   or item.startswith('src-') for item in ids):
                raise ValueError('practical_model_identity_collision')
