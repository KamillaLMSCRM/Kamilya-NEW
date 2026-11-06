"""Bounded text, table, and speaker-note extraction for native PowerPoint sources."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
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


class PresentationNeedsTextError(RuntimeError):
    """A visual-only slide requires recognition before a source review."""


@dataclass(frozen=True)
class Presentation:
    markdown: str
    slides: int
    tables: int


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
            key = _tag(ns, 'id')
            if key in node.attrib:
                node.set(_tag(normal, 'id'), node.attrib.pop(key))
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


def read_presentation(path: str) -> Presentation:
    with open(path, 'rb') as source:
        preflight_ooxml(source, '.pptx')
        with ZipFile(source) as archive:
            main = 'ppt/presentation.xml'
            relations = _links(archive, main, 'slide', _SLIDE)
            ids = _xml(archive, main).findall(f'{_tag(_P, "sldIdLst")}/{_tag(_P, "sldId")}')
            order = [relations.get(node.get(_tag(_R, 'id'), '')) for node in ids]
            if not order or None in order or len(set(order)) != len(order):
                raise ValueError('PowerPoint slide order is missing or invalid')
            blocks: list[str] = []
            characters = tables = 0
            for number, part in enumerate(order, start=1):
                if part is None:  # narrowed for type checkers; rejected above
                    raise ValueError('Invalid PowerPoint slide target')
                slide = _xml(archive, part)
                tree = slide.find(f'{_tag(_P, "cSld")}/{_tag(_P, "spTree")}')
                if tree is None:
                    raise ValueError('PowerPoint slide content is missing')
                sections, count = _shape_content(tree)
                visual_only = not sections and any(node.tag in {_tag(_P, 'pic'), _tag(_P, 'graphicFrame')}
                                                   for node in tree.iter())
                if visual_only:
                    raise PresentationNeedsTextError('PowerPoint slide needs a text source')
                tables += count
                notes: list[str] = []
                notes_parts = _links(archive, part, 'notesSlide', _NOTES)
                if len(notes_parts) > 1:
                    raise ValueError('PowerPoint slide has multiple note sources')
                for notes_part in notes_parts.values():
                    for shape in _xml(archive, notes_part).iter(_tag(_P, 'sp')):
                        placeholder = shape.find(f'.//{_tag(_P, "ph")}')
                        if placeholder is not None and placeholder.get('type') == 'body':
                            notes.extend(_paragraphs(shape))
                if sections or notes:
                    body = '\n\n'.join([f'## [Slide {number}]', *sections, *(['### [Speaker notes]', *notes] if notes else [])])
                    characters += len(body) + 2
                    if characters > _MAX_RENDERED:
                        raise ValueError('PowerPoint content exceeds the safe conversion size')
                    blocks.append(body)
            return Presentation('\n\n'.join(blocks), len(order), tables)
