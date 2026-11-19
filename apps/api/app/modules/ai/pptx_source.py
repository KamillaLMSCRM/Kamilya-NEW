"""Bounded text, table, and speaker-note extraction for native PowerPoint sources."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from defusedxml import ElementTree

from app.modules.documents.archive_preflight import preflight_ooxml

_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
_STRICT = {
    'http://purl.oclc.org/ooxml/presentationml/main': _P,
    'http://purl.oclc.org/ooxml/drawingml/main': _A,
    'http://purl.oclc.org/ooxml/officeDocument/relationships': _R,
}
# Parser safety boundaries, not product quotas. The shared archive preflight
# also caps the compressed package's expanded size and entry count.
_MAX_XML = 8 * 1024 * 1024
_MAX_RENDERED = 4_000_000
_SLIDE = re.compile(r'ppt/slides/[^/]+\.xml')
_NOTES = re.compile(r'ppt/notesSlides/[^/]+\.xml')
_MEDIA = re.compile(r'ppt/media/[^/]+')


class PresentationNeedsTextError(RuntimeError):
    """A visual-only slide requires recognition before a source review."""


@dataclass(frozen=True)
class Presentation:
    markdown: str
    slides: int
    tables: int


@dataclass(frozen=True)
class SlidePicture:
    member: str
    data: bytes


@dataclass(frozen=True)
class PresentationSlide:
    number: int
    member: str
    text: str
    tables: int
    needs_text: bool
    pictures: tuple[SlidePicture, ...]


def _tag(namespace: str, name: str) -> str:
    return f'{{{namespace}}}{name}'


def _xml(archive: ZipFile, name: str) -> Element:
    entry = archive.getinfo(name)
    if entry.file_size > _MAX_XML:
        raise ValueError('PowerPoint XML exceeds the safe conversion size')
    root = ElementTree.fromstring(archive.read(entry), forbid_dtd=True)
    for node in root.iter():
        if node.tag.startswith('{'):
            ns, local = node.tag[1:].split('}', 1)
            if ns in _STRICT:
                node.tag = _tag(_STRICT[ns], local)
        for ns, normal in _STRICT.items():
            for attribute in ('id', 'embed', 'link'):
                key = _tag(ns, attribute)
                if key in node.attrib:
                    node.set(_tag(normal, attribute), node.attrib.pop(key))
    return root


def _links(archive: ZipFile, part: str, kind: str, target_pattern: re.Pattern[str]) -> dict[str, str]:
    folder, basename = posixpath.split(part)
    rels = posixpath.join(folder, '_rels', basename + '.rels')
    try:
        root = _xml(archive, rels)
    except KeyError:
        return {}
    result: dict[str, str] = {}
    for element in root.findall(_tag(_PKG, 'Relationship')):
        if element.get('Type') not in {_R + '/' + kind, 'http://purl.oclc.org/ooxml/officeDocument/relationships/' + kind}:
            continue
        identifier, raw = element.get('Id', ''), element.get('Target', '')
        target = posixpath.normpath(raw.lstrip('/') if raw.startswith('/') else posixpath.join(folder, raw))
        if (element.get('TargetMode', 'Internal') != 'Internal' or not target_pattern.fullmatch(target)
                or not identifier or identifier in result or '\\' in raw or '?' in raw or '#' in raw):
            raise ValueError('Invalid internal PowerPoint relationship')
        result[identifier] = target
    return result


def _paragraphs(node: Element) -> list[str]:
    return [value for paragraph in node.iter(_tag(_A, 'p'))
            if (value := ''.join((child.text or '') if child.tag == _tag(_A, 't') else ' '
                for child in paragraph.iter() if child.tag in {_tag(_A, 't'), _tag(_A, 'br')}).strip())]


def _shape_content(tree: Element) -> tuple[list[str], int]:
    sections: list[str] = []
    tables = 0
    for shape in tree:
        if shape.tag == _tag(_P, 'grpSp'):
            children, count = _shape_content(shape)
            sections.extend(children)
            tables += count
        elif shape.tag in {_tag(_P, 'sp'), _tag(_P, 'cxnSp')}:
            sections.extend(_paragraphs(shape))
        elif shape.tag == _tag(_P, 'graphicFrame'):
            for table in shape.iter(_tag(_A, 'tbl')):
                rows = [[' '.join(_paragraphs(cell)).replace('|', r'\|') for cell in row.findall(_tag(_A, 'tc'))]
                        for row in table.findall(_tag(_A, 'tr'))]
                if rows and any(any(row) for row in rows):
                    width = len(rows[0])
                    if not width or any(len(row) != width for row in rows):
                        raise ValueError('Invalid PowerPoint table dimensions')
                    data = [rows[0], ['---'] * width, *rows[1:]]
                    sections.append('\n'.join('| ' + ' | '.join(row) + ' |' for row in data))
                    tables += 1
    return sections, tables


def _slide_pictures(
    archive: ZipFile, part: str, tree: Element, max_image_bytes: int, image_cache: dict[str, bytes],
) -> tuple[SlidePicture, ...]:
    for frame in tree.iter(_tag(_P, 'graphicFrame')):
        if frame.find(f'.//{_tag(_A, "tbl")}') is None:
            raise ValueError('native_source_unsupported_visual')
    if any(node.tag in {_tag(_A, 'videoFile'), _tag(_A, 'audioFile'), _tag(_P, 'oleObj')}
           for node in tree.iter()):
        raise ValueError('native_source_unsupported_visual')
    try:
        targets = _links(archive, part, 'image', _MEDIA)
    except ValueError as exc:
        raise ValueError('native_source_unsupported_visual') from exc
    pictures = []
    used_blips = set()
    for picture in tree.iter(_tag(_P, 'pic')):
        blip = picture.find(f'{_tag(_P, "blipFill")}/{_tag(_A, "blip")}')
        if blip is None or blip.get(_tag(_R, 'link')) or blip.get(_tag(_R, 'embed'), '') not in targets:
            raise ValueError('native_source_unsupported_visual')
        used_blips.add(blip)
        crop = picture.find(f'{_tag(_P, "blipFill")}/{_tag(_A, "srcRect")}')
        if crop is not None and any(value not in {'0', '0%'} for value in crop.attrib.values()):
            raise ValueError('native_source_unsupported_visual')
        member = targets[blip.get(_tag(_R, 'embed'), '')]
        if member not in image_cache:
            try:
                entry = archive.getinfo(member)
            except KeyError as exc:
                raise ValueError('native_source_unsupported_visual') from exc
            if not 0 < entry.file_size <= max_image_bytes:
                raise ValueError('native_image_byte_limit')
            image_cache[member] = archive.read(entry)
        pictures.append(SlidePicture(member, image_cache[member]))
    if any(blip not in used_blips for blip in tree.iter(_tag(_A, 'blip'))):
        raise ValueError('native_source_unsupported_visual')
    return tuple(pictures)


def iter_presentation_slides(
    source: BinaryIO, *, max_image_bytes: int | None = None,
) -> Iterator[PresentationSlide]:
    """Read slides in presentation order. Load embedded pictures only for source preparation."""
    preflight_ooxml(source, '.pptx')
    with ZipFile(source) as archive:
        main = 'ppt/presentation.xml'
        relations = _links(archive, main, 'slide', _SLIDE)
        ids = _xml(archive, main).findall(f'{_tag(_P, "sldIdLst")}/{_tag(_P, "sldId")}')
        order = [relations.get(node.get(_tag(_R, 'id'), '')) for node in ids]
        if not order or None in order or len(set(order)) != len(order):
            raise ValueError('PowerPoint slide order is missing or invalid')
        characters = 0
        image_cache: dict[str, bytes] = {}
        for number, part in enumerate(order, start=1):
            if part is None:
                raise ValueError('Invalid PowerPoint slide target')
            slide = _xml(archive, part)
            tree = slide.find(f'{_tag(_P, "cSld")}/{_tag(_P, "spTree")}')
            if tree is None:
                raise ValueError('PowerPoint slide content is missing')
            sections, tables = _shape_content(tree)
            needs_text = not sections and any(node.tag in {_tag(_P, 'pic'), _tag(_P, 'graphicFrame')}
                                             for node in tree.iter())
            notes: list[str] = []
            notes_parts = _links(archive, part, 'notesSlide', _NOTES)
            if len(notes_parts) > 1:
                raise ValueError('PowerPoint slide has multiple note sources')
            for notes_part in notes_parts.values():
                for shape in _xml(archive, notes_part).iter(_tag(_P, 'sp')):
                    placeholder = shape.find(f'.//{_tag(_P, "ph")}')
                    if placeholder is not None and placeholder.get('type') == 'body':
                        notes.extend(_paragraphs(shape))
            body = ''
            if sections or notes:
                body = '\n\n'.join([f'## [Slide {number}]', *sections,
                                    *(['### [Speaker notes]', *notes] if notes else [])])
                characters += len(body) + 2
                if characters > _MAX_RENDERED:
                    raise ValueError('PowerPoint content exceeds the safe conversion size')
            pictures = (_slide_pictures(archive, part, tree, max_image_bytes, image_cache)
                        if max_image_bytes is not None else ())
            background = slide.find(f'{_tag(_P, "cSld")}/{_tag(_P, "bg")}')
            if (max_image_bytes is not None and background is not None
                    and background.find(f'.//{_tag(_A, "blip")}') is not None):
                raise ValueError('native_source_unsupported_visual')
            yield PresentationSlide(number, part, body, tables, needs_text, pictures)


def read_presentation(path: str) -> Presentation:
    blocks: list[str] = []
    count = tables = 0
    with open(path, 'rb') as source:
        for slide in iter_presentation_slides(source):
            if slide.needs_text:
                raise PresentationNeedsTextError('PowerPoint slide needs a text source')
            if slide.text:
                blocks.append(slide.text)
            tables += slide.tables
            count += 1
    return Presentation('\n\n'.join(blocks), count, tables)
