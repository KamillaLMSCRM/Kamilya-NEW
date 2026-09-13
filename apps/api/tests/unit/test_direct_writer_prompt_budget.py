from types import SimpleNamespace

import pytest

from app.modules.ai import direct_source as direct_source_module
from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.direct_source import (
    MAX_DIRECT_WRITER_PROMPT_CHARS,
    MAX_DIRECT_WRITER_SOURCE_CHARS,
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
    DirectSourceError,
    write_direct_course,
)


def fixture(document_count=1, heading_chars=480, title='Catalog'):
    documents = []
    for d in range(document_count):
        doc_id = f'doc-{d}'
        chunks = tuple(DirectSourceChunk(
            chunk_id=f'{d}-{i}', doc_id=doc_id, doc_name='catalog.xlsx', title='Catalog',
            headings=('h' * heading_chars,), text=f'item-{d}-{i}:'.ljust(1000, 'x'),
            source_revision='document:' + 'a' * 64, chunk_index=i,
        ) for i in range(24))
        documents.append(DirectSourceDocument(doc_id, 'Catalog', 'catalog.xlsx', 'general',
                                              'document:' + 'a' * 64, chunks))
    corpus = DirectSourceCorpus('synthetic', tuple(documents), 24000 * document_count, 24 * document_count)
    structure = CourseStructure(title, modules=[Module('Module', lessons=[
        Lesson('Lesson', source_doc_ids=[d.doc_id for d in documents])])])
    return corpus, structure


class Spy:
    def __init__(self):
        self.messages = []

    async def ainvoke(self, messages):
        self.messages.append(messages)
        assert sum(len(m['content']) for m in messages) <= MAX_DIRECT_WRITER_PROMPT_CHARS
        return SimpleNamespace(content='Item source lesson content.')


@pytest.mark.asyncio
@pytest.mark.parametrize('document_count', [1, 2])
async def test_writer_budgets_whole_serialized_chunks_and_preserves_documents(document_count):
    corpus, structure = fixture(document_count)
    llm = Spy()
    content = await write_direct_course(llm, corpus, structure)
    lesson = content.modules[0].lessons[0]
    prompt = llm.messages[0][-1]['content']
    assert {r['doc_id'] for r in lesson.source_references} == set(corpus.document_ids)
    assert sum(map(len, lesson.source_chunks)) <= MAX_DIRECT_WRITER_SOURCE_CHARS
    assert len(lesson.source_chunks) == len(lesson.source_references)
    originals = {c.text for d in corpus.documents for c in d.chunks}
    assert all(c in originals and c in prompt for c in lesson.source_chunks)
    assert all((c.text in prompt) == (c.text in lesson.source_chunks) for d in corpus.documents for c in d.chunks)


@pytest.mark.asyncio
async def test_writer_uses_a_grounded_prefix_when_one_source_chunk_exceeds_the_prompt_budget():
    source_text = ('Item source lesson content. ' * 2000).strip()
    chunk = DirectSourceChunk(
        chunk_id='oversized-0',
        doc_id='doc-0',
        doc_name='scanned-rules.pdf',
        title='Rules',
        headings=('Microcredit rules',),
        text=source_text,
        source_revision='document:' + 'b' * 64,
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        'synthetic',
        (DirectSourceDocument(
            'doc-0',
            'Rules',
            'scanned-rules.pdf',
            'general',
            chunk.source_revision,
            (chunk,),
        ),),
        len(source_text),
        1,
    )
    structure = CourseStructure('Rules', modules=[Module('Module', lessons=[
        Lesson('Lesson', source_doc_ids=['doc-0'])
    ])])
    llm = Spy()

    content = await write_direct_course(llm, corpus, structure)

    lesson = content.modules[0].lessons[0]
    grounded_prefix = lesson.source_chunks[0]
    assert len(llm.messages) == 1
    assert 0 < len(grounded_prefix) <= MAX_DIRECT_WRITER_SOURCE_CHARS
    assert len(grounded_prefix) < len(source_text)
    assert source_text.startswith(grounded_prefix)
    assert grounded_prefix in llm.messages[0][-1]['content']
    assert len(lesson.source_references) == 1
    assert lesson.source_references[0]['doc_id'] == 'doc-0'
    assert lesson.source_references[0]['doc_name'] == 'scanned-rules.pdf'
    assert lesson.source_references[0]['headings'] == ['Microcredit rules']


@pytest.mark.asyncio
async def test_writer_rebudgets_source_when_quality_retry_adds_correction(monkeypatch):
    corpus, structure = fixture()
    llm = Spy()
    admissions = iter((False, True))

    def fake_quality(**_kwargs):
        accepted = next(admissions)
        return SimpleNamespace(
            accepted=accepted,
            reason_codes=() if accepted else ('unsupported_relationship_claim',),
        )

    monkeypatch.setattr(direct_source_module, 'evaluate_lesson_quality', fake_quality)

    content = await write_direct_course(llm, corpus, structure)

    assert len(content.modules[0].lessons) == 1
    assert len(llm.messages) == 2
    assert 'CORRECTION REQUIRED' in llm.messages[1][-1]['content']
    assert all(
        sum(len(message['content']) for message in invocation)
        <= MAX_DIRECT_WRITER_PROMPT_CHARS
        for invocation in llm.messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('kwargs', [{'heading_chars': 33000}, {'title': 'x' * 33000}])
async def test_unrepresentable_writer_request_fails_before_provider(kwargs):
    corpus, structure = fixture(**kwargs)
    llm = Spy()
    with pytest.raises(DirectSourceError, match='direct_source_prompt_budget_exceeded'):
        await write_direct_course(llm, corpus, structure)
    assert not llm.messages
