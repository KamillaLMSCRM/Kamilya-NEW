"""Meaning-preserving admission controls, no provider or database."""
import json
from dataclasses import asdict, replace
from hashlib import sha256

import pytest

from app.modules.ai.source_editorial_document import bind_source_editorial_document, source_editorial_document_from_dict
from app.modules.ai.source_editorial_model import prepare_source_working_edition, source_editorial_result_valid
from app.modules.source_editorial_review.analysis import analyze

AXES = ('digits_preserved', 'numeric_values_preserved', 'units_preserved',
        'operators_preserved', 'negation_modality_preserved',
        'coordination_logic_preserved', 'actors_preserved', 'content_complete',
        'no_inferred_list_logic')
DI = ('До предоставления микрокредита физическому лицу, не связанного '
      'с осуществлением предпринимательской деятельности, проводить оценку пригодности микрокредита.')


async def run_patch(original, before, after, evidence=None, category='grammar',
                    source_id='synthetic', chunk_id='unit'):
    async def complete(messages):
        payload = json.loads(messages[1]['content'])
        if 'proposal_sha256' not in payload:
            return {'patches':[{'alias':'change', 'before':before, 'after':after,
                    'category':category, 'reason':'Correct agreement',
                    'supporting_original_context_quotes':[original]}], 'unresolved':[]}
        row = {'patch_alias':payload['patches'][0]['alias'], 'relation':'preserved',
               'reason':'Preserved', **dict.fromkeys(AXES, True)}
        if evidence is not None:
            row['editorial_evidence'] = evidence
        return {'proposal_sha256':payload['proposal_sha256'], 'rows':[row]}
    return await prepare_source_working_edition(original, source_id=source_id, chunk_id=chunk_id, complete_json=complete)


@pytest.mark.asyncio
async def test_saved_di_blanket_preservation_flags_cannot_admit_reattachment():
    result = await run_patch(DI, 'связанного', 'связанному')
    assert result.edition.working_text == DI
    assert not result.edition.applied_patch_aliases


def proof(head, before_text, after_text, relation='predicate', **overrides):
    return {'original_status':'defective', 'necessity':'required',
            'head_before':head, 'head_after':head,
            'relation_before':relation, 'relation_after':relation, **overrides}


@pytest.mark.asyncio
@pytest.mark.parametrize(('original','before','after','head','relation'), [
    ('Сотрудники проверяет документы.', 'проверяет', 'проверяют', 'Сотрудники', 'predicate'),
    ('Служебная записка подготовлен.', 'подготовлен', 'подготовлена', 'записка', 'predicate'),
    ('Сотрудник подписывает договором.', 'договором', 'договор', 'подписывает', 'object'),
    ('Операотр проверяет документы.', 'Операотр', 'Оператор', 'проверяет', 'subject'),
    ('Операотр', 'Операотр', 'Оператор', None, 'standalone'),
    ('Сотрудник находится в новой кабинете.', 'новой', 'новом', 'кабинете', 'modifier'),
    ('Операотр оформляет квитанцию.', 'Операотр', 'Оператор', None, 'standalone'),
])
async def test_necessary_corrections_preserve_literal_dependency(original, before, after, head, relation):
    result = await run_patch(original, before, after, proof(head, before, after, relation))
    assert result.edition.working_text == original.replace(before, after)
    assert result.edition.applied_patch_aliases
    assert result.model_calls == 2
    assert source_editorial_result_valid(result, source_text=original, source_id='synthetic', chunk_id='unit')
    tampered = replace(result, review_wire={**result.review_wire, 'rows':[]})
    assert not source_editorial_result_valid(tampered, source_text=original, source_id='synthetic', chunk_id='unit')


@pytest.mark.asyncio
@pytest.mark.parametrize('override', [
    {'original_status':'valid'}, {'original_status':'uncertain'},
    {'necessity':'optional'}, {'necessity':'uncertain'},
    {'head_before':None}, {'head_after':None},
    {'head_after':'документы'}, {'relation_after':'object'},
    {'head_before':'не существует'},
    {'head_before':None,'head_after':None,'relation_before':'standalone','relation_after':'standalone'},
    {'head_before':'Сотрудни','head_after':'Сотрудни'},
])
async def test_uncertain_optional_unbound_or_changed_attachments_never_apply(override):
    original = 'Сотрудники проверяет документы.'
    result = await run_patch(original, 'проверяет', 'проверяют', proof('Сотрудники','проверяет','проверяют',**override))
    assert result.edition.working_text == original


@pytest.mark.asyncio
async def test_valid_di_reattachment_and_forged_necessity_are_both_withheld():
    evidence = proof('предоставления микрокредита','связанного','связанному','modifier')
    evidence['head_after'] = 'физическому лицу'
    result = await run_patch(DI, 'связанного', 'связанному', evidence)
    assert result.edition.working_text == DI  # Even forged necessity cannot change the head address.
    evidence['original_status'] = 'valid'
    evidence['necessity'] = 'optional'
    result = await run_patch(DI, 'связанного', 'связанному', evidence)
    assert result.edition.working_text == DI


@pytest.mark.asyncio
async def test_actual_luna_false_necessity_and_wrong_original_head_are_vetoed():
    # Saved source-only Luna reply claimed BOTH forms modify the dative person.
    evidence = proof('физическому лицу','связанного','связанному','modifier')
    result = await run_patch(DI, 'связанного', 'связанному', evidence)
    assert result.edition.working_text == DI
    assert result.review_wire['rows'][0]['relation']=='preserved'  # Keep the false model vote as evidence.
    assert 'existing_inflection_reading' in result.edition.gaps[0].reason


@pytest.mark.asyncio
async def test_same_failure_class_in_other_wording_and_category_is_not_allowed():
    text = 'Сотрудник передает клиенту договор, подписанный руководителем.'
    result = await run_patch(text,'подписанный','подписанному',
                             proof('клиенту','подписанный','подписанному','modifier'),category='typo')
    assert result.edition.working_text == text


@pytest.mark.asyncio
async def test_possible_remote_noun_reading_is_conservatively_withheld_not_rewritten():
    original='В новой кабинете находится копия папки.'
    result=await run_patch(original,'новой','новом',proof('кабинете','новой','новом','modifier'))
    # No full syntactic parser: a compatible distant noun is enough to abstain.
    # Preserve the source rather than claim that this ambiguity has been solved.
    assert result.edition.working_text == original
    assert not result.edition.applied_patch_aliases


@pytest.mark.asyncio
async def test_missing_dictionary_abstains_without_model_retry(monkeypatch):
    def unavailable():
        raise OSError('unavailable')
    monkeypatch.setattr('app.modules.ai.assessment_preservation._morph',unavailable)
    original='Сотрудники проверяет документы.'
    result=await run_patch(original,'проверяет','проверяют',proof('Сотрудники','проверяет','проверяют'))
    assert result.edition.working_text == original and result.model_calls == 2


@pytest.mark.asyncio
async def test_serialized_policy_removal_or_downgrade_cannot_launder_new_review():
    source_revision='document:'+sha256(DI.encode()).hexdigest()
    result=await run_patch(DI,'связанного','связанному',
        proof('физическому лицу','связанного','связанному','modifier'),
        source_id=source_revision,chunk_id='editorial-doc:synthetic-doc')
    document=bind_source_editorial_document(document_id='synthetic-doc',source_revision=source_revision,
        recognized_text=DI,result=result)
    payload=json.loads(json.dumps(asdict(document)))
    assert source_editorial_document_from_dict(payload)==document
    del payload['result']['ingress_policy']
    with pytest.raises(ValueError):
        source_editorial_document_from_dict(payload)
    payload['result']['ingress_policy']='source-editorial-guarded-ingress-v2'
    with pytest.raises(ValueError):
        source_editorial_document_from_dict(payload)


@pytest.mark.asyncio
async def test_word_identical_layout_keeps_existing_two_call_path():
    result = await run_patch('Keep the  receipt.', 'the  receipt', 'the receipt', category='layout')
    assert result.edition.working_text == 'Keep the receipt.' and result.model_calls == 2


@pytest.mark.asyncio
async def test_punctuation_is_not_a_whitespace_bypass():
    original = 'Казнить нельзя, помиловать.'
    result = await run_patch(original, 'нельзя, помиловать', ', нельзя помиловать', category='layout')
    assert result.edition.working_text == original


@pytest.mark.asyncio
async def test_native_analysis_retains_original_without_creating_false_human_issue():
    async def complete(messages):
        payload = json.loads(messages[1]['content'])
        if 'proposal_sha256' not in payload:
            return {'patches':[{'alias':'case', 'before':'связанного', 'after':'связанному',
                    'category':'grammar','reason':'Agree with person',
                    'supporting_original_context_quotes':[DI]}], 'unresolved':[]}
        return {'proposal_sha256':payload['proposal_sha256'], 'rows':[
            {'patch_alias':'case','relation':'preserved','reason':'Agreement', **dict.fromkeys(AXES,True)}],
                'source_questions':[]}
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
    result = await analyze(DI, source_id='source', document_id='document', complete_json=complete, checkpoint=checkpoint)
    assert result['original'] == DI and result['automatic'] == [] and result['issues'] == []
    assert result['model_calls'] == 2
    assert result['rejected_automatic'][0]['id'] == 'a0-case'
    assert 'necessity_or_attachment' in result['rejected_automatic'][0]['reason']
    async def never(_):
        pytest.fail('Completed v5 checkpoint must not call the model again')
    replay = await analyze(DI, source_id='source', document_id='document', complete_json=never, retained=saved)
    assert replay['rejected_automatic'] == result['rejected_automatic']
    assert replay['model_calls'] == 0 and replay['automatic'] == []
