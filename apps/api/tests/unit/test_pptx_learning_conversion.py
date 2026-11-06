import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.ai.ingestion import DocumentConverter
from app.modules.documents.archive_preflight import ArchivePreflightError, preflight_ooxml
from app.modules.source_editorial_review.analysis import analyze

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'


def deck(path: Path, *, image_only: bool = False, external: bool = False) -> None:
    with zipfile.ZipFile(path, 'w') as package:
        package.writestr('[Content_Types].xml', '<Types/>')
        package.writestr('ppt/presentation.xml',
            f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>'
            '<p:sldId r:id="rId2"/><p:sldId r:id="rId1"/></p:sldIdLst></p:presentation>')
        target = 'https://example.invalid/slide' if external else 'slides/slide2.xml'
        mode = ' TargetMode="External"' if external else ''
        package.writestr('ppt/_rels/presentation.xml.rels', f'<Relationships xmlns="{PKG}">'
            f'<Relationship Id="rId1" Type="{R}/slide" Target="slides/slide1.xml"/>'
            f'<Relationship Id="rId2" Type="{R}/slide" Target="{target}"{mode}/></Relationships>')
        for n, tree in [(1, '<p:sp><a:p><a:r><a:t>Return in 72 hours</a:t></a:r></a:p></p:sp>'),
                        (2, '<p:pic/>' if image_only else '<p:sp><a:p><a:r><a:t>Return in 24 hours</a:t></a:r></a:p></p:sp>'
                            '<p:graphicFrame><a:tbl><a:tr><a:tc><a:p><a:r><a:t>Kit</a:t></a:r></a:p></a:tc>'
                            '<a:tc><a:p><a:r><a:t>Receipt</a:t></a:r></a:p></a:tc></a:tr></a:tbl></p:graphicFrame>')]:
            package.writestr(f'ppt/slides/slide{n}.xml', f'<p:sld xmlns:p="{P}" xmlns:a="{A}">'
                f'<p:cSld><p:spTree>{tree}</p:spTree></p:cSld></p:sld>')
        package.writestr('ppt/slides/_rels/slide2.xml.rels', f'<Relationships xmlns="{PKG}">'
            f'<Relationship Id="rId3" Type="{R}/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>')
        package.writestr('ppt/notesSlides/notesSlide1.xml', f'<p:notes xmlns:p="{P}" xmlns:a="{A}">'
            '<p:cSld><p:spTree><p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
            '<a:p><a:r><a:t>Keep the receipt.</a:t></a:r></a:p></p:sp></p:spTree></p:cSld></p:notes>')


@pytest.mark.asyncio
async def test_pptx_keeps_slide_order_notes_and_table_without_remote_converter(tmp_path):
    path = tmp_path / 'training.pptx'
    deck(path)
    result = await DocumentConverter().convert(str(path))
    content = result['markdown']
    assert content.index('Return in 24 hours') < content.index('Return in 72 hours')
    assert '| Kit | Receipt |' in content
    assert 'Keep the receipt.' in content
    assert result['metadata']['pages'] == 2
    assert result['metadata']['tables'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('option', ['external', 'image_only'])
async def test_pptx_does_not_claim_reviewable_content_when_slides_are_external_or_image_only(tmp_path, option):
    path = tmp_path / 'training.pptx'
    deck(path, **{option: True})
    with pytest.raises(ValueError if option == 'external' else RuntimeError):
        await DocumentConverter().convert(str(path))


def test_ooxml_preflight_rejects_word_archive_renamed_to_pptx(tmp_path):
    path = tmp_path / 'renamed.pptx'
    with zipfile.ZipFile(path, 'w') as package:
        package.writestr('[Content_Types].xml', '<Types/>')
        package.writestr('word/document.xml', '<document/>')
    with path.open('rb') as source, pytest.raises(ArchivePreflightError, match='missing a required'):
        preflight_ooxml(source, '.pptx')


@pytest.mark.asyncio
async def test_pptx_review_anchors_conflict_to_extracted_slide_text(tmp_path):
    path = tmp_path / 'training.pptx'
    deck(path)
    blob = path.read_bytes()
    storage = Mock()
    storage.get_bytes.return_value = blob
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), lifecycle_status='active',
        content_sha256=hashlib.sha256(blob).hexdigest(), s3_key='synthetic-pptx',
        filename=path.name, title='Training', category='general', size=len(blob))
    corpus = await build_direct_source_corpus([doc], tenant_id=doc.tenant_id, storage=storage)
    original = corpus.documents[0].source_text
    assert original is not None

    async def complete(messages):
        request = json.loads(messages[1]['content'])
        assert 'Return in 24 hours' in messages[1]['content'] and 'Return in 72 hours' in messages[1]['content']
        if 'proposal_sha256' not in request:
            return {'patches': [], 'unresolved': []}
        return {'proposal_sha256': request['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': 'Return in 24 hours', 'category': 'conflict', 'reason': 'Should the return be in 24 or 72 hours?'},
        ]}

    result = await analyze(original, source_id=corpus.documents[0].source_revision,
                           document_id=str(doc.id), complete_json=complete)
    issue, = result['issues']
    assert issue['category'] == 'conflict' and original[issue['start']:issue['end']] == issue['quote']
    assert result['original'] == original and result['automatic'] == []
