import hashlib
import io
import re
import zipfile

import pypdfium2
import pytest
from docx import Document
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, RectangleObject

from app.modules.source_preparation.extraction import extract_native_source


def png(color):
    output = io.BytesIO()
    Image.new("RGB", (12, 10), color).save(output, format="PNG")
    return output.getvalue()


def extract(blob, filename="source.docx", **limits):
    return extract_native_source(blob, filename, hashlib.sha256(blob).hexdigest(),
                                 max_image_bytes=limits.get("max_image_bytes", 100000),
                                 max_image_pixels=limits.get("max_image_pixels", 10000))


def docx_file():
    document = Document()
    document.add_heading("Heading", level=1)
    p = document.add_paragraph("before ")
    p.add_run().add_picture(io.BytesIO(png("red")))
    p.add_run(" between ")
    p.add_run().add_picture(io.BytesIO(png("red")))
    p.add_run(" after")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Operation"
    table.cell(0, 1).text = "Amount"
    cell = table.cell(1, 0)
    cell.paragraphs[0].add_run("payment ")
    cell.paragraphs[0].add_run().add_picture(io.BytesIO(png("blue")))
    table.cell(1, 1).text = "100"
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def rewrite_zip(blob, replacements):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blob)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            data = source.read(entry.filename)
            target.writestr(entry, replacements(entry.filename, data))
    return output.getvalue()


def test_ordered_images_table_and_duplicate_content():
    blob = docx_file()
    before = hashlib.sha256(blob).hexdigest()
    result = extract(blob)
    assert result is not None
    assert [b.kind for b in result.blocks] == ["heading", "text", "image", "text", "image", "text", "table"]
    assert [b.text for b in result.blocks[:-1]] == ["Heading", "before ", "", " between ", "", " after"]
    images = [b for b in result.blocks if b.kind == "image"]
    table = result.blocks[-1]
    assert images[0].asset_ids == images[1].asset_ids != table.asset_ids
    assert len(result.assets) == 2 and "table" in result.assets[1].locator
    assert table.text == f"| Operation | Amount |\n| --- | --- |\n| payment {{{{{table.asset_ids[0]}}}}} | 100 |"
    assert result.assets[1].locator["row"] == 1 and result.assets[1].locator["cell"] == 0
    assert all(a.asset_id == "asset-" + hashlib.sha256(a.data).hexdigest() for a in result.assets)
    assert len({b.block_id for b in result.blocks}) == len(result.blocks)
    assert result == extract(blob)
    assert hashlib.sha256(blob).hexdigest() == before


def test_rejects_bad_relationship_and_corrupt_image():
    blob = docx_file()
    def break_relationship(name, data):
        if name == "word/document.xml":
            data, count = re.subn(b'r:embed="[^"]+"', b'r:embed="missing"', data, count=1)
            assert count == 1
        return data

    missing = rewrite_zip(blob, break_relationship)
    with pytest.raises(ValueError, match="relationship"):
        extract(missing)
    corrupt = rewrite_zip(blob, lambda name, data: b"not an image" if name.startswith("word/media/") else data)
    with pytest.raises(ValueError, match="native_image_invalid"):
        extract(corrupt)


def test_rejects_linked_image():
    def make_link(name, data):
        if name == "word/document.xml":
            data, count = re.subn(b'r:embed="[^"]+"', b'r:link="external"', data, count=1)
            assert count == 1
        return data

    with pytest.raises(ValueError, match="external_or_missing_relationship"):
        extract(rewrite_zip(docx_file(), make_link))


def test_image_limits_and_bad_original_hash():
    blob = docx_file()
    with pytest.raises(ValueError, match="pixel_limit"):
        extract(blob, max_image_pixels=100)
    with pytest.raises(ValueError, match="byte_limit"):
        extract(blob, max_image_bytes=10)
    with pytest.raises(ValueError, match="sha256_mismatch"):
        extract_native_source(blob, "x.docx", "0" * 64, max_image_bytes=100000, max_image_pixels=10000)


def test_pdf_nine_image_only_pages_preserve_page_identity():
    images = [Image.new("RGB", (20, 20), (i * 20, 0, 0)) for i in range(9)]
    output = io.BytesIO()
    images[0].save(output, format="PDF", save_all=True, append_images=images[1:])
    result = extract(output.getvalue(), "scan.pdf")
    assert result is not None and result.page_count == 9
    assert [block.page for block in result.blocks] == list(range(1, 10))
    assert all(block.kind == "page" and block.asset_ids for block in result.blocks)
    assert len({block.block_id for block in result.blocks}) == 9
    assert all(not block.locator.get("rendered_page") for block in result.blocks)


def test_pdf_vector_table_borders_are_rendered_for_review():
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b"10 10 m 90 90 l S")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    result = extract(output.getvalue(), "vector.pdf")
    assert result is not None and len(result.blocks) == 1
    block = result.blocks[0]
    assert block.kind == "page" and block.text == "" and block.page == 1
    assert block.locator["rendered_page"] and block.locator["original_sha256"] == hashlib.sha256(output.getvalue()).hexdigest()
    assert block.asset_ids == (result.assets[0].asset_id,)
    assert Image.open(io.BytesIO(result.assets[0].data)).convert("RGB").getpixel((50, 50)) != (255, 255, 255)


def test_pdf_annotation_static_appearance_is_rendered_with_text(monkeypatch):
    def forbid_forms(*args, **kwargs):
        raise AssertionError("PDF form environment must not be initialized")
    monkeypatch.setattr(pypdfium2.PdfDocument, "init_forms", forbid_forms)
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 10 Tf 10 70 Td (Text) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    appearance = DecodedStreamObject()
    appearance.set_data(b"1 0 0 rg 0 0 30 30 re f")
    appearance.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                       NameObject("/BBox"): RectangleObject([0, 0, 30, 30])})
    annotation = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Square"),
        NameObject("/Rect"): RectangleObject([20, 20, 50, 50]), NameObject("/F"): NumberObject(4),
        NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(appearance)})})
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    output = io.BytesIO()
    writer.write(output)
    result = extract(output.getvalue(), "annotation.pdf")
    assert result is not None and result.blocks[0].kind == "page" and result.blocks[0].text == ""
    pixels = Image.open(io.BytesIO(result.assets[0].data)).convert("RGB")
    assert pixels.getpixel((30, 70))[0] > 200 and pixels.getpixel((30, 70))[1] < 50
    assert any(r < 100 and g < 100 and b < 100 for r, g, b in pixels.crop((0, 15, 60, 35)).get_flattened_data())


def test_pdf_interactive_widget_is_explicitly_unavailable():
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    widget = DictionaryObject({NameObject("/Subtype"): NameObject("/Widget"),
                               NameObject("/Rect"): RectangleObject([10, 10, 50, 50])})
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(widget)])
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="source_preparation_pdf_render_widget_unsupported"):
        extract(output.getvalue(), "widget.pdf")


def test_pdf_form_xobject_is_rendered():
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    form = DecodedStreamObject()
    form.set_data(b"0 0 1 rg 10 10 40 40 re f")
    form.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                 NameObject("/BBox"): RectangleObject([0, 0, 100, 100])})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Fm"): writer._add_object(form)})})
    content = DecodedStreamObject()
    content.set_data(b"/Fm Do")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    result = extract(output.getvalue(), "form.pdf")
    assert result is not None and result.blocks[0].locator["rendered_page"]
    pixel = Image.open(io.BytesIO(result.assets[0].data)).convert("RGB").getpixel((20, 80))
    assert pixel[2] > 200 and pixel[0] < 50


def test_pdf_render_respects_pixel_and_byte_limits():
    writer = PdfWriter()
    page = writer.add_blank_page(width=120, height=120)
    content = DecodedStreamObject()
    content.set_data(b"10 10 m 100 100 l S")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="native_image_pixel_limit"):
        extract(output.getvalue(), "vector.pdf", max_image_pixels=10000)
    with pytest.raises(ValueError, match="native_image_byte_limit"):
        extract(output.getvalue(), "vector.pdf", max_image_pixels=50000, max_image_bytes=10)


def test_other_formats_delegate():
    assert extract(b"hello", "source.txt") is None
