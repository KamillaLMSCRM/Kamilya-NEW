import hashlib
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import build_practical_source_packet


def packet_for(*texts):
    documents = tuple(DirectSourceDocument(f'doc{i}', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(text.encode()).hexdigest(), (), source_text=text)
        for i, text in enumerate(texts))
    return build_practical_source_packet(DirectSourceCorpus('tenant', documents, sum(map(len, texts)), 0))


def test_structural_groups_cover_order_parent_children_and_multiple_documents():
    packet = packet_for('# 1. First\n1. Parent\n1) First child\n2) Second child\n'
                        '# 2. Second\n2. Other\n', 'Independent document.')
    grouping = audit_units(packet)
    flattened = [ref for _, refs in grouping.groups for ref in refs]
    assert flattened == [b.block_id for b in packet.blocks if b.text.strip()]
    assert [name for name, _ in grouping.groups] == [f'U{i}' for i in range(1, len(grouping.groups) + 1)]
    parent = next(i for i, b in enumerate(packet.blocks) if b.text.startswith('1. Parent'))
    parent_refs = [b.block_id for b in packet.blocks[parent:parent + 3]]
    assert any(all(ref in refs for ref in parent_refs) for _, refs in grouping.groups)
    assert all(len({next(b.doc_id for b in packet.blocks if b.block_id == ref) for ref in refs}) == 1
               for _, refs in grouping.groups)
    assert audit_units(packet) == grouping


def test_table_header_remains_with_first_row_and_unstructured_fallback():
    packet = packet_for('# 1. Table\n| Role | Action |\n| --- | --- |\n| A | Sign |\n| B | Record |\n'
                        '# 2. Other\nDone.\n')
    groups = audit_units(packet).groups
    header = next(b.block_id for b in packet.blocks if b.text.startswith('| Role'))
    row = next(b.block_id for b in packet.blocks if b.text.startswith('| A'))
    assert any(header in refs and row in refs for _, refs in groups)
    plain = packet_for('Introduction.\n\n1. First paragraph.\n2. Second paragraph.')
    assert [refs for _, refs in audit_units(plain).groups] == [(b.block_id,) for b in plain.blocks]


def test_blank_blocks_keep_raw_custody_without_teaching_refs():
    packet = packet_for('\n\n# 1. First\nText.\n# 2. Second\nOther.\n')
    assert any(not b.text.strip() for b in packet.blocks)
    assert [ref for _, refs in audit_units(packet).groups for ref in refs] == [
        b.block_id for b in packet.blocks if b.text.strip()]
    assert ''.join(b.text for b in packet.blocks).startswith('\n\n')


def test_packet_reordering_rejected():
    packet = packet_for('First.\n\nSecond.')
    with pytest.raises(ValueError):
        audit_units(replace(packet, blocks=tuple(reversed(packet.blocks))))
