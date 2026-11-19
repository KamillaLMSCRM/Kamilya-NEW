import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from PIL import Image

from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.ai.ingestion import DocumentConverter
from app.modules.documents.archive_preflight import ArchivePreflightError, preflight_ooxml
from app.modules.source_editorial_review.analysis import analysis_failure_code, analyze
from app.modules.source_preparation.extraction import extract_native_source
from app.modules.source_preparation.lesson_assets import approved_asset_inventory, bind_lesson_assets
from app.modules.source_preparation.preparation import prepare_native_source

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


def with_screenshots(path, *, image_only=False, external=False, crop=False):
    deck(path, image_only=image_only)
    output = io.BytesIO()
    image = io.BytesIO()
    Image.new('RGB', (12, 10), 'blue').save(image, format='PNG')
    relationship = ('Target="https://example.invalid/picture" TargetMode="External"'
                    if external else 'Target="../media/screenshot.png"')
    crop_xml = '<a:srcRect l="10000"/>' if crop else ''
    picture = (f'<p:pic><p:blipFill xmlns:r="{R}"><a:blip r:embed="rIdImage"/>'
               f'{crop_xml}</p:blipFill></p:pic>')
    with zipfile.ZipFile(path) as original, zipfile.ZipFile(output, 'w') as modified:
        for name in original.namelist():
            data = original.read(name)
            if name in ('ppt/slides/slide2.xml', 'ppt/slides/slide1.xml'):
                data = data.decode().replace('<p:pic/>', '').replace('</p:spTree>', picture + '</p:spTree>')
            if name == 'ppt/slides/_rels/slide2.xml.rels':
                data = data.decode().replace('</Relationships>',
                    f'<Relationship Id="rIdImage" Type="{R}/image" {relationship}/></Relationships>')
            modified.writestr(name, data)
        modified.writestr('ppt/slides/_rels/slide1.xml.rels', f'<Relationships xmlns="{PKG}">'
            f'<Relationship Id="rIdImage" Type="{R}/image" Target="../media/screenshot.png"/></Relationships>')
        modified.writestr('ppt/media/screenshot.png', image.getvalue())
    return output.getvalue()


def prepare_pptx(blob, *, max_image_bytes=100_000):
    return extract_native_source(blob, 'training.pptx', hashlib.sha256(blob).hexdigest(),
                                 max_image_bytes=max_image_bytes, max_image_pixels=10_000)


@pytest.mark.parametrize('image_only', [False, True])
def test_source_preparation_retains_raster_bytes_notes_and_slide_coordinates(tmp_path, image_only):
    blob = with_screenshots(tmp_path / 'training.pptx', image_only=image_only)
    source = prepare_pptx(blob)
    assert source is not None
    first, second = [[block for block in source.blocks if block.page == index] for index in (1, 2)]
    assert source.page_count == 2
    assert [block.kind for block in first] == (['page', 'text'] if image_only else ['text', 'image'])
    assert len(source.assets) == 1
    asset = source.assets[0]
    assert asset.locator['slide'] == 1 and asset.locator['member'] == 'ppt/slides/slide2.xml'
    assert asset.mime_type == 'image/png' and (asset.width, asset.height) == (12, 10)
    assert hashlib.sha256(asset.data).hexdigest() == asset.sha256
    assert 'Keep the receipt.' in (first[1] if image_only else first[0]).text
    if not image_only:
        assert '| Kit | Receipt |' in first[0].text
    picture = first[0] if image_only else first[1]
    assert picture.asset_ids == second[1].asset_ids == (asset.asset_id,)
    assert second[1].locator['slide'] == 2
    assert second[1].locator['member'] == 'ppt/slides/slide1.xml'


@pytest.mark.parametrize('option', ['external', 'crop'])
def test_source_preparation_blocks_pictures_without_faithful_local_pixels(tmp_path, option):
    blob = with_screenshots(tmp_path / 'training.pptx', **{option: True})
    with pytest.raises(ValueError, match='native_source_unsupported_visual') as caught:
        prepare_pptx(blob)
    assert analysis_failure_code(caught.value) == 'source_review_unsupported_visual'


def test_source_preparation_reads_no_oversized_image_and_keeps_text_only_path(tmp_path):
    path = tmp_path / 'training.pptx'
    deck(path)
    assert prepare_pptx(path.read_bytes()) is None
    blob = with_screenshots(path)
    with pytest.raises(ValueError, match='native_image_byte_limit'):
        prepare_pptx(blob, max_image_bytes=4)


@pytest.mark.asyncio
async def test_pptx_screenshot_reaches_prepared_source_with_verifiable_slide_locator(tmp_path):
    blob = with_screenshots(tmp_path / 'training.pptx', image_only=True)
    source = prepare_pptx(blob)
    assert source is not None
    asset, = source.assets
    statement = 'Check the cabinet seal before opening it.'

    async def read_image(messages):
        image = next(item for item in messages[1]['content'] if item['type'] == 'image_url')
        expected = base64.b64encode(asset.data).decode('ascii')
        assert image['image_url']['url'] == 'data:image/png;base64,' + expected
        return {'images': [{'id': asset.asset_id, 'caption': 'Cabinet label', 'kind': 'figure',
                            'text': statement, 'description': 'A work instruction label', 'uncertainties': []}]}

    async def verify_image(messages):
        hints = json.loads(messages[1]['content'][0]['text'])
        return {'images': [hint['proposed_reading'] for hint in hints]}

    async def partition(messages):
        blocks = json.loads(messages[1]['content'])['blocks']
        return {'parts': [{'title': 'Cabinet access', 'role': 'learning', 'reason': 'One procedure',
                          'first_block': blocks[0]['id'], 'last_block': blocks[-1]['id']}]}

    persist = AsyncMock(return_value='source-assets/qa/screenshot.png')
    prepared = await prepare_native_source(
        source, original_sha256=hashlib.sha256(blob).hexdigest(), complete=partition,
        visual_complete=read_image, visual_review_complete=verify_image, checkpoint=AsyncMock(),
        persist_asset=persist, retained={}, vision_batch_size=2, preview_chars=600,
    )
    selected_ids = [part.id for part in prepared.parts]
    selected_text = prepared.selected(selected_ids)[0]
    assert statement in selected_text and 'Keep the receipt.' in selected_text
    screenshot_markdown = f'![Cabinet label](source-asset:{asset.asset_id})'
    recognized = next(block for block in prepared.blocks if block.page == 1)
    assert screenshot_markdown in recognized.text
    assert '## [Slide 1]' in recognized.text and statement in recognized.text
    assert recognized.locator['slide'] == 1 and recognized.asset_ids == [asset.asset_id]

    document = str(uuid4())
    inventory = approved_asset_inventory({document: SimpleNamespace(
        preparation=prepared.binding(selected_ids),
        source_revision='document:' + hashlib.sha256(blob).hexdigest(),
        recognized_text=selected_text,
    )})
    course_id, lesson_id = uuid4(), uuid4()
    body, assets = bind_lesson_assets(screenshot_markdown, inventory, course_id=course_id, lesson_id=lesson_id)
    assert f'/v1/courses/{course_id}/lessons/{lesson_id}/source-assets/{asset.asset_id}' in body
    assert [item['sha256'] for item in assets] == [asset.sha256]
    persist.assert_awaited_once_with(asset)
