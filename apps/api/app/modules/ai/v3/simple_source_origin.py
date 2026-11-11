"""Project validated visual origins onto exact approved source blocks.

Origin labels describe provenance, not authority, correctness or entailment.
"""
from __future__ import annotations

from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.practical_contract import PracticalSourcePacket
from app.modules.ai.v3.simple_course_editor import _source_context
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, validated_preparation


def _prepared_ranges(approved: ApprovedEditorialDocument) -> list[tuple[int, int, str, str | None]]:
    package, ids = validated_preparation(approved.preparation, approved.source_revision.removeprefix('document:'),
                                        approved.recognized_text)
    _, _, blocks = package.selected(ids)
    assets = {item.id: item for item in package.assets}
    ranges: list[tuple[int, int, str, str | None]] = []
    position = 0
    first = True
    for block in blocks:
        if not block.text.strip():
            continue
        if not first:
            ranges.append((position, position + 2, 'unclassified_text', None))
            position += 2
        first = False
        text = block.text
        parts: list[tuple[int, int, str, str | None]] = []
        ambiguous = False
        if block.kind == 'page_text':
            scan = [assets[asset_id] for asset_id in block.asset_ids if assets[asset_id].kind == 'scan']
            if len(block.asset_ids) == len(scan) == 1 and text in scan[0].text:
                parts.append((0, len(text), 'scanned_document_text', scan[0].id))
            else:
                ambiguous = True
        else:
            for asset_id in dict.fromkeys(block.asset_ids):
                asset = assets[asset_id]
                if asset.kind == 'scan':
                    # Mixed scan/text blocks have no exact generated marker.
                    ambiguous = True
                    break
                caption = asset.caption.replace('[', '(').replace(']', ')').replace('\n', ' ')
                prefix = (f'![{caption}](source-asset:{asset.id})\n'
                          'Изображение — пример из исходника.\nРаспознанные надписи: ')
                description_label = '\nОписание изображения (не нормативный текст): '
                exact = prefix + asset.text + description_label + asset.description
                start = text.find(exact)
                if start < 0 or text.find(exact, start + 1) >= 0:
                    ambiguous = True
                    break
                middle = start + len(prefix) + len(asset.text)
                parts.extend([(start, middle, 'visual_ocr', asset.id),
                              (middle, start + len(exact), 'visual_description', asset.id)])
            marker = text.find('source-asset:')
            while marker >= 0:
                if not any(start <= marker < end for start, end, _, _ in parts):
                    ambiguous = True
                    break
                marker = text.find('source-asset:', marker + 1)
        parts.sort()
        if ambiguous or any(parts[i][0] < parts[i - 1][1] for i in range(1, len(parts))):
            ranges.append((position, position + len(text), 'unclassified_text', None))
        else:
            cursor = 0
            for start, end, origin, part_asset in parts:
                if cursor < start:
                    ranges.append((position + cursor, position + start, 'document_body', None))
                ranges.append((position + start, position + end, origin, part_asset))
                cursor = end
            if cursor < len(text):
                ranges.append((position + cursor, position + len(text), 'document_body', None))
        position += len(text)
    if position != len(approved.recognized_text):
        raise ValueError('simple_source_origin_binding_invalid')
    return ranges


def _working_ranges(approved: ApprovedEditorialDocument) -> list[tuple[int, int, str, str | None]]:
    raw = _prepared_ranges(approved)
    output: list[tuple[int, int, str, str | None]] = []
    cursor = 0
    for span in approved.spans:
        start, end = span['raw_start'], span['raw_end']
        ws, we = span['working_start'], span['working_end']
        while cursor < len(raw) and raw[cursor][1] <= start:
            cursor += 1
        touched = []
        index = cursor
        while index < len(raw) and raw[index][0] < end:
            left, right, origin, asset = raw[index]
            touched.append((max(start, left), min(end, right), origin, asset))
            index += 1
        if span['item_id'] is not None:
            # Edited visual or mixed-origin text cannot inherit pixel-level provenance.
            unique = {(origin, asset) for _, _, origin, asset in touched}
            origin, asset = (next(iter(unique)) if len(unique) == 1 else ('unclassified_text', None))
            if origin != 'document_body':
                origin, asset = 'unclassified_text', None
            output.append((ws, we, origin, asset))
        else:
            for left, right, origin, asset in touched:
                output.append((ws + left - start, ws + right - start, origin, asset))
    return output


def source_origin_blocks(packet: PracticalSourcePacket, corpus: DirectSourceCorpus) -> list[dict[str, Any]]:
    """Return literal, ordered segments; unavailable mappings remain unclassified."""
    _source_context(packet, corpus, {})  # verifies packet, tenant and approved source custody
    by_doc = {doc.doc_id: doc for doc in corpus.documents}
    mappings: dict[str, list[tuple[int, int, str, str | None]] | None] = {}
    for doc in corpus.documents:
        approved = doc.editorial_document
        if not isinstance(approved, ApprovedEditorialDocument):
            raise ValueError('simple_source_origin_approval_invalid')
        mappings[doc.doc_id] = None if approved.preparation is None else _working_ranges(approved)
    result: list[dict[str, Any]] = []
    offsets = {doc.doc_id: 0 for doc in corpus.documents}
    for block in packet.blocks:
        ranges = mappings[block.doc_id]
        segments: list[dict[str, Any]] = []
        diagnostic: list[str] = []
        if ranges is None:
            segments.append({'origin': 'unclassified_text', 'text': block.text})
            diagnostic.append('preparation_not_available')
        else:
            cursor = offsets[block.doc_id]
            while cursor < len(ranges) and ranges[cursor][1] <= block.start:
                cursor += 1
            offsets[block.doc_id] = cursor
            while cursor < len(ranges) and ranges[cursor][0] < block.end:
                start, end, origin, asset = ranges[cursor]
                left, right = max(start, block.start), min(end, block.end)
                if left < right:
                    text = by_doc[block.doc_id].source_text[left:right]  # type: ignore[index]
                    row: dict[str, Any] = {'origin': origin, 'text': text}
                    if asset is not None:
                        row['asset_id'] = asset
                    segments.append(row)
                cursor += 1
            if ''.join(row['text'] for row in segments) != block.text:
                segments = [{'origin': 'unclassified_text', 'text': block.text}]
                diagnostic.append('origin_mapping_incomplete')
            elif any(row['origin'] == 'unclassified_text' and row['text'].strip() for row in segments):
                diagnostic.append('origin_mapping_ambiguous')
        result.append({'id': block.block_id, 'document_id': block.doc_id,
                       'segments': segments, 'diagnostics': diagnostic})
    return result
