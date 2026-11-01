from app.modules.ai.v3.service import _validate_answer_completeness, _validate_question_entailment


def _review(missing):
    statuses = ['SUPPORTED', 'CONTRADICTED', 'CONTRADICTED', 'CONTRADICTED']
    return {'options': [
        {'index': i, 'verdict': status,
         'claims': [{'claim': 'action', 'status': status, 'reason': 'source'}],
         'summary': 'reviewed',
         'omitted_required_elements': missing if i == 0 else []}
        for i, status in enumerate(statuses)]}


def test_supported_correct_option_with_required_omissions_is_not_accepted():
    # Saved D07: actor providing explanation and exact stop-list object are omitted.
    review = _review(['объяснительная с эксперта-оценщика',
                      'внесение несогласованных залоговых билетов в стоп-лист'])
    assert not _validate_question_entailment(review, [True, False, False, False])[0]


def test_supported_correct_option_without_omissions_remains_eligible():
    assert _validate_question_entailment(_review([]), [True, False, False, False])[0]


def test_missing_or_malformed_completeness_result_is_not_accepted():
    for invalid in (None, "", [""], [12]):
        review = _review([])
        review['options'][0]['omitted_required_elements'] = invalid
        assert not _validate_question_entailment(review, [True, False, False, False])[0]


def test_independent_completeness_rejects_saved_d07_omissions_and_invalid_results():
    assert not _validate_answer_completeness({'answers': [{'index': 0, 'omissions': [
        'объяснительная с эксперта-оценщика', 'билеты в стоп-лист']}]})[0]
    for invalid in ({}, {'answers': []}, {'answers': [{'index': 0}]},
                    {'answers': [{'index': 0, 'omissions': ['']}]},
                    {'answers': [{'index': 1, 'omissions': []}]},
                    {'answers': [{'index': 0, 'omissions': []}, {'index': 0, 'omissions': []}]}):
        assert not _validate_answer_completeness(invalid)[0]
    assert not _validate_answer_completeness({'answers': [{'index': 0, 'omissions': []}]})[0]
    assert _validate_answer_completeness({'answers': [{'index': 0, 'omissions': []}], 'explanation_review': {"verdict": "SUPPORTED", "claims": [{"claim": "Fact", "status": "SUPPORTED", "reason": "Source"}], "summary": "Checked"}})[0]
