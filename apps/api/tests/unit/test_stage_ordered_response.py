import hashlib

import pytest

from app.modules.ai.v3.stage_checkpoint import _digest, ordered_response_fields, restore_ordered_response


def test_ordered_capture_restores_jsonb_reordered_response_and_legacy_absence():
    response = {'long_key': {'z': 1, 'a': 2}, 'id': 'value'}
    reordered = {'id': 'value', 'long_key': {'a': 2, 'z': 1}}
    value = {'response_sha256': _digest(response), **ordered_response_fields(response)}
    restored = restore_ordered_response(value, reordered)
    assert list(restored) == ['long_key', 'id'] and list(restored['long_key']) == ['z', 'a']
    assert restore_ordered_response({'response_sha256': _digest(reordered)}, reordered) is reordered


@pytest.mark.parametrize('raw', [
    '{"id":"other"}', '{"id":"value","id":"value"}', '{ "id":"value"}',
    '{"id":NaN}', '[]', '{', 'null',
])
def test_ordered_capture_rejects_tampering_and_noncanonical_json(raw):
    response = {'id': 'value'}
    with pytest.raises(ValueError, match='v3_stage_checkpoint_invalid'):
        restore_ordered_response({'response_sha256': _digest(response), 'response_ordered_json': raw,
                                  'response_ordered_sha256': hashlib.sha256(raw.encode()).hexdigest()}, response)


def test_ordered_capture_rejects_custody_combination_and_wrong_digest():
    response = {'id': 'value'}
    value = {'response_sha256': _digest(response), **ordered_response_fields(response)}
    with pytest.raises(ValueError, match='v3_stage_checkpoint_invalid'):
        restore_ordered_response({**value, 'author_custody': {}}, response)
    with pytest.raises(ValueError, match='v3_stage_checkpoint_invalid'):
        restore_ordered_response({**value, 'response_sha256': '0' * 64}, response)


def test_order_change_is_detected_even_when_values_are_equal():
    response = {'z': 1, 'a': 2}
    value = {'response_sha256': _digest(response), **ordered_response_fields(response)}
    value['response_ordered_json'] = '{"a":2,"z":1}'
    with pytest.raises(ValueError, match='v3_stage_checkpoint_invalid'):
        restore_ordered_response(value, response)
