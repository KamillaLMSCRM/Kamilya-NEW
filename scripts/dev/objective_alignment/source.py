"""DEV adapter retaining narrative notes in sections which also contain tables.

The production builder remains untouched. Preserve its section roles so an
auxiliary catalogue cannot be silently promoted to primary learning material.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from app.modules.ai.evidence_engine.application import (
    _locator, _merge_overlapping_chunks, build_evidence_source,
)
from app.modules.ai.evidence_engine.models import SourceFact


def build_complete_source(corpus):
    bundle = build_evidence_source(corpus)
    sections = []
    for section in bundle.document.sections:
        if ":sheet:" not in section.section_id:
            sections.append(section)
            continue
        existing = {" ".join(f.value.split()) for f in section.facts}
        additions = []
        for document in corpus.documents:
            if not section.section_id.startswith(document.doc_id + ":sheet:"):
                continue
            matching = [chunk for chunk in document.chunks if
                        next(iter(reversed(chunk.headings)), "").removeprefix("[Worksheet] ").strip().casefold()
                        == section.title.casefold()]
            merged = _merge_overlapping_chunks(sorted(matching, key=lambda chunk: chunk.chunk_index))
            # Tables are already admitted with exact row/column ownership by the
            # production builder. Only recover adjacent narrative, not table data.
            lines = [line if not (line.lstrip().startswith(("|", "#", "<!--", "!["))) else ""
                     for line in merged.splitlines()]
            for index, paragraph in enumerate(re.split(r"\n\s*\n", "\n".join(lines)), 1):
                value = paragraph.strip()
                normalized = " ".join(value.split())
                if not value or normalized in existing:
                    continue
                existing.add(normalized)
                identity = "\0".join((document.doc_id, section.title, value)).encode()
                additions.append(SourceFact(
                    fact_id="note-" + hashlib.sha256(identity).hexdigest()[:16],
                    subject=f"{section.title}: общие правила", attribute="Примечание к таблице",
                    value=value,
                    source_locator=_locator(doc_id=document.doc_id, source_revision=document.source_revision,
                                            section=section.title, paragraph=index)))
        sections.append(replace(section, facts=section.facts + tuple(additions)))
    return replace(bundle, document=replace(bundle.document, sections=tuple(sections)))
