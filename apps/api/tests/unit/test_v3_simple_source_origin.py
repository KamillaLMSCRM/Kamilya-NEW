import copy
import hashlib
import json
from dataclasses import replace

import pytest

from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.simple_source_origin import source_origin_blocks
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from app.modules.source_preparation.domain import PreparedSource, SourceAsset, SourceBlock, SourcePart, digest
from tests.unit.test_v3_simple_course_editor import fixture


def asset(symbol, text='same OCR', description='visual description', kind='form'):
    sha = symbol * 64
    return SourceAsset(id='asset-' + sha, sha256=sha, mime_type='image/png', width=3, height=3,
        storage_key='private-storage-path', caption='Caption ' + symbol, kind=kind, text=text,
        description=description, uncertainties=[], locator={})


def figure(item):
    return (f'![{item.caption}](source-asset:{item.id})\nИзображение — пример из исходника.\n'
            f'Распознанные надписи: {item.text}\nОписание изображения (не нормативный текст): {item.description}')


def make_corpus(blocks, assets, *, selected=None, edits=None):
    corpus, _ = fixture()
    original_hash = 'c' * 64
    parts = []
    for block in blocks:
        part_id = 'part-' + digest(original_hash + block.id + block.id)[:24]
        parts.append(SourcePart(id=part_id, title='Part', role='learning', reason='Context',
                                first_block=block.id, last_block=block.id))
    package = PreparedSource(original_blob_sha256=original_hash, blocks=blocks, assets=assets, parts=parts)
    selected = selected if selected is not None else list(range(len(parts)))
    binding = package.binding([parts[i].id for i in selected])
    recognized = package.selected(binding['selected_part_ids'])[0]
    working, spans = render_text(recognized, edits or [])
    doc = corpus.documents[0]
    revision = 'document:' + original_hash
    approved = ApprovedEditorialDocument(doc.doc_id, revision, 'approval', recognized, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {}, preparation=binding)
    assert approved.valid(document_id=doc.doc_id, source_revision=revision)
    doc = replace(doc, source_revision=revision, source_text=working, editorial_document=approved)
    return replace(corpus, documents=(doc,))


def source_block(index, text, *, kind='paragraph', asset_ids=()):
    return SourceBlock(id='block-' + f'{index:024x}', text=text, kind=kind, asset_ids=list(asset_ids))


def flattened(result):
    return [segment for row in result for segment in row['segments']]


def test_mixed_figures_keep_exact_text_and_distinguish_repeated_ocr():
    first, second = asset('a'), asset('b')
    text = 'Operative rule.\n\n' + figure(first) + '\n\n' + figure(second)
    corpus = make_corpus([source_block(1, text, asset_ids=[first.id, second.id])], [first, second])
    packet = build_practical_source_packet(corpus)
    snapshot = copy.deepcopy(corpus)
    result = source_origin_blocks(packet, corpus)
    assert [(r['id'], r['document_id']) for r in result] == [(b.block_id, b.doc_id) for b in packet.blocks]
    assert all(''.join(s['text'] for s in row['segments']) == block.text
               for row, block in zip(result, packet.blocks, strict=True))
    segments = flattened(result)
    assert {s['asset_id'] for s in segments if s['origin'] == 'visual_ocr'} == {first.id, second.id}
    assert {s['asset_id'] for s in segments if s['origin'] == 'visual_description'} == {first.id, second.id}
    assert any(s['origin'] == 'document_body' and 'Operative rule.' in s['text'] for s in segments)
    assert 'private-storage-path' not in json.dumps(result) and corpus == snapshot


def test_selected_scan_and_unselected_asset_are_separate():
    scan, unused = asset('a', text='Scanned paragraph.', kind='scan'), asset('b')
    blocks = [source_block(1, 'Scanned paragraph.', kind='page_text', asset_ids=[scan.id]),
              source_block(2, figure(unused), asset_ids=[unused.id])]
    corpus = make_corpus(blocks, [scan, unused], selected=[0])
    result = source_origin_blocks(build_practical_source_packet(corpus), corpus)
    assert flattened(result) == [{'origin': 'scanned_document_text', 'text': 'Scanned paragraph.', 'asset_id': scan.id}]
    assert unused.id not in json.dumps(result)


def test_scan_text_not_in_visual_reading_is_unclassified():
    scan = asset('a', text='Different page reading.', kind='scan')
    corpus = make_corpus([source_block(1, 'Unmatched paragraph.', kind='page_text', asset_ids=[scan.id])], [scan])
    result = source_origin_blocks(build_practical_source_packet(corpus), corpus)
    assert flattened(result) == [{'origin': 'unclassified_text', 'text': 'Unmatched paragraph.'}]
    assert result[0]['diagnostics'] == ['origin_mapping_ambiguous']


def test_unlinked_illustration_is_not_misclassified_as_document_body():
    item = asset('a')
    other = asset('b')
    text = figure(item) + '\n\n' + figure(other)
    corpus = make_corpus([source_block(1, text, asset_ids=[item.id])], [item, other])
    result = source_origin_blocks(build_practical_source_packet(corpus), corpus)
    assert all(row['origin'] == 'unclassified_text' for row in flattened(result))


def test_no_preparation_and_ambiguous_visual_fail_closed():
    corpus, packet = fixture()
    result = source_origin_blocks(packet, corpus)
    assert all(row['diagnostics'] == ['preparation_not_available'] for row in result)
    assert all(s['origin'] == 'unclassified_text' for s in flattened(result))
    item = asset('a')
    text = 'Rule.\n\n' + figure(item) + '\n\n' + figure(item)
    corpus = make_corpus([source_block(1, text, asset_ids=[item.id])], [item])
    packet = build_practical_source_packet(corpus)
    result = source_origin_blocks(packet, corpus)
    assert all(s['origin'] == 'unclassified_text' for s in flattened(result))
    assert any(row['diagnostics'] == ['origin_mapping_ambiguous'] for row in result)


def test_edits_keep_body_origin_but_do_not_guess_visual_or_cross_origin():
    item = asset('a')
    text = 'RULE BEFORE.\n\n' + figure(item)
    visual = text.index(item.text)
    edits = [{'id': 'body', 'start': 0, 'end': 4, 'before': 'RULE', 'after': 'NEW RULE'},
             {'id': 'visual', 'start': visual, 'end': visual + len(item.text),
              'before': item.text, 'after': 'edited OCR'}]
    corpus = make_corpus([source_block(1, text, asset_ids=[item.id])], [item], edits=edits)
    packet = build_practical_source_packet(corpus)
    segments = flattened(source_origin_blocks(packet, corpus))
    assert any(s['origin'] == 'document_body' and s['text'] == 'NEW RULE' for s in segments)
    assert any(s['origin'] == 'unclassified_text' and s['text'] == 'edited OCR' for s in segments)
    assert any(s['origin'] == 'visual_description' for s in segments)
    boundary_start = text.index('BEFORE')
    boundary_end = text.index('пример') + len('пример')
    crossed = [{'id': 'cross', 'start': boundary_start, 'end': boundary_end,
                'before': text[boundary_start:boundary_end], 'after': 'combined edit'}]
    changed = make_corpus([source_block(1, text, asset_ids=[item.id])], [item], edits=crossed)
    changed_segments = flattened(source_origin_blocks(build_practical_source_packet(changed), changed))
    assert any(s['origin'] == 'unclassified_text' and s['text'] == 'combined edit' for s in changed_segments)


def test_invalid_or_stale_preparation_is_rejected():
    item = asset('a')
    corpus = make_corpus([source_block(1, figure(item), asset_ids=[item.id])], [item])
    packet = build_practical_source_packet(corpus)
    doc = corpus.documents[0]
    tampered = copy.deepcopy(doc.editorial_document.preparation)
    tampered['sha256'] = '0' * 64
    altered = replace(corpus, documents=(replace(doc, editorial_document=replace(doc.editorial_document,
                                                                                    preparation=tampered)),))
    with pytest.raises(ValueError, match='simple_source_custody_invalid'):
        source_origin_blocks(packet, altered)


def test_many_distinct_source_blocks_remain_exact_and_ordered():
    blocks = [source_block(i + 1, f'Independent paragraph {i}.') for i in range(1000)]
    corpus = make_corpus(blocks, [])
    packet = build_practical_source_packet(corpus)
    result = source_origin_blocks(packet, corpus)
    assert len(result) == len(packet.blocks)
    assert all(''.join(s['text'] for s in row['segments']) == block.text
               for row, block in zip(result, packet.blocks, strict=True))
