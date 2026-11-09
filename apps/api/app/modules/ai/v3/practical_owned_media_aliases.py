"""Reversible source-image aliases for an already owned course snapshot.

The caller must establish tenant/RLS ownership of the snapshot and protect the
returned manifest from untrusted modification. This module does not fetch assets
or establish approval or semantic correctness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, cast
from uuid import UUID

from app.modules.source_preparation.lesson_assets import _IMAGE as _CANONICAL_IMAGE

_UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
_SERVED = re.compile(rf'/v1/courses/({_UUID})/lessons/({_UUID})/source-assets/(asset-[a-f0-9]{{64}})')
_HTML_IMAGE = re.compile(r'<\s*img\b', re.IGNORECASE)
_MEDIA_MENTION = re.compile(r'''source-asset:[^\s)\]"'<>]*|/v1/courses/[^\s)\]"'<>]*/source-assets/[^\s)\]"'<>]*''')


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def _balanced(text: str, start: int, opening: str, closing: str) -> int:
    depth = 1
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == '\n' or char == '\r':
            break
        if char == '\\':
            index += 2
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError('owned_media_unsupported_markdown')


def _images(text: str) -> list[dict[str, Any]]:
    """Retain complete inline image syntax, including opaque external URLs."""
    if _HTML_IMAGE.search(text):
        raise ValueError('owned_media_html_image_unsupported')
    rows = []
    index = 0
    while index < len(text):
        if text[index] == '\\':
            index += 2
            continue
        if not text.startswith('![', index):
            index += 1
            continue
        start = index
        close = _balanced(text, index + 1, '[', ']')
        alt = text[index + 2:close]
        end = close + 1
        url = None
        if end < len(text) and text[end] == '(':
            destination_end = _balanced(text, end, '(', ')')
            url = text[end + 1:destination_end]
            end = destination_end + 1
        else:
            # Reference targets are defined elsewhere and cannot be preserved
            # merely by comparing the visible image markup.
            raise ValueError('owned_media_reference_image_unsupported')
        rows.append({'start': start, 'end': end, 'markdown': text[start:end], 'alt': alt, 'url': url})
        index = end
    return rows


def _course(course: Any) -> list[dict[str, Any]]:
    if type(course) is not dict or type(course.get('lessons')) is not list:
        raise ValueError('owned_media_course_invalid')
    lessons = course['lessons']
    if any(type(row) is not dict or type(row.get('id')) is not str or not row['id'].strip()
           or type(row.get('content')) is not str for row in lessons):
        raise ValueError('owned_media_course_invalid')
    if len({row['id'] for row in lessons}) != len(lessons):
        raise ValueError('owned_media_lesson_identity_invalid')
    return cast(list[dict[str, Any]], lessons)


def _plain_mentions(text: str, images: list[dict[str, Any]]) -> list[str]:
    """Keep non-image media-like references unchanged without rewriting them."""
    return [match.group() for match in _MEDIA_MENTION.finditer(text)
            if not any(image['start'] <= match.start() < image['end'] for image in images)]


def _uuid(value: Any) -> UUID:
    try:
        if type(value) not in (str, UUID):
            raise ValueError
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError('owned_media_owner_identity_invalid') from None


def canonicalize_owned_media(course: dict[str, Any], *, owned_course_id: str | UUID,
                             owned_lesson_ids: dict[str, str | UUID]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return model-view copy and trusted manifest for this caller-owned snapshot."""
    lessons = _course(course)
    owner = _uuid(owned_course_id)
    if type(owned_lesson_ids) is not dict or set(owned_lesson_ids) != {row['id'] for row in lessons}:
        raise ValueError('owned_media_lesson_mapping_invalid')
    owners = {key: _uuid(value) for key, value in owned_lesson_ids.items()}
    if len(set(owners.values())) != len(owners):
        raise ValueError('owned_media_lesson_mapping_invalid')
    model = copy.deepcopy(course)
    manifest_lessons = []
    for original, output in zip(lessons, model['lessons'], strict=True):
        entries = []
        replacements = []
        original_images = _images(original['content'])
        for index, image in enumerate(original_images):
            markdown, url = image['markdown'], image['url']
            served = _SERVED.fullmatch(url) if url is not None else None
            canonical = _CANONICAL_IMAGE.fullmatch(markdown)
            kind, asset_id, proposed = 'opaque', None, markdown
            if served is not None:
                if _uuid(served[1]) != owner or _uuid(served[2]) != owners[original['id']]:
                    raise ValueError('owned_media_foreign_served_url')
                kind, asset_id = 'served', served[3]
                proposed = f"![{image['alt']}](source-asset:{asset_id})"
            elif canonical is not None:
                kind, asset_id = 'canonical', canonical[2]
            elif url is not None and url.startswith('source-asset:'):
                raise ValueError('owned_media_invalid_canonical_url')
            entries.append({'occurrence': index, 'alt': image['alt'], 'original_markdown': markdown,
                            'original_url': url, 'asset_id': asset_id, 'kind': kind,
                            'model_markdown': proposed})
            if proposed != markdown:
                replacements.append((image['start'], image['end'], proposed))
        text = original['content']
        for start, end, replacement in reversed(replacements):
            text = text[:start] + replacement + text[end:]
        output['content'] = text
        manifest_lessons.append({'lesson_id': original['id'], 'owned_lesson_id': str(owners[original['id']]),
                                 'plain_media_mentions': _plain_mentions(original['content'], original_images),
                                 'images': entries})
    manifest = {'version': 'owned-media-alias-v1', 'owned_course_id': str(owner),
                'source_course_fingerprint': _digest(course), 'model_course_fingerprint': _digest(model),
                'lessons': manifest_lessons}
    return model, manifest


def restore_owned_media(proposal: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restore exact original image markup after strict per-lesson occurrence checks."""
    lessons = _course(proposal)
    if (type(manifest) is not dict or manifest.get('version') != 'owned-media-alias-v1'
            or type(manifest.get('lessons')) is not list
            or [row['id'] for row in lessons] != [row.get('lesson_id') for row in manifest['lessons']]):
        raise ValueError('owned_media_manifest_invalid')
    restored = copy.deepcopy(proposal)
    total, changed = 0, 0
    for row, saved, output in zip(lessons, manifest['lessons'], restored['lessons'], strict=True):
        images = _images(row['content'])
        if _plain_mentions(row['content'], images) != saved['plain_media_mentions']:
            raise ValueError('owned_media_plain_reference_changed')
        expected = saved['images']
        if len(images) != len(expected):
            raise ValueError('owned_media_image_count_changed')
        replacements = []
        for index, (image, original) in enumerate(zip(images, expected, strict=True)):
            if (original['occurrence'] != index or image['alt'] != original['alt']
                    or image['markdown'] not in (original['original_markdown'], original['model_markdown'])):
                raise ValueError('owned_media_image_identity_changed')
            if image['markdown'] != original['original_markdown']:
                replacements.append((image['start'], image['end'], original['original_markdown']))
                changed += 1
            total += 1
        text = row['content']
        for start, end, replacement in reversed(replacements):
            text = text[:start] + replacement + text[end:]
        output['content'] = text
    return restored, {'original_course_fingerprint': manifest['source_course_fingerprint'],
                      'restored_course_fingerprint': _digest(restored), 'images_checked': total,
                      'aliases_restored': changed, 'semantic_acceptance': False}
