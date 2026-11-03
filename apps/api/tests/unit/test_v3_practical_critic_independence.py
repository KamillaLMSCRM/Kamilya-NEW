"""Critics receive original evidence, not another model's interpretation."""
import json

from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import practical_review_messages
from app.modules.ai.v3.practical_source_audit import source_audit_messages
from app.modules.ai.v3.practical_source_reader import source_reader_parts, validate_source_read
from tests.unit.test_v3_practical_review import example
from tests.unit.test_v3_practical_source_reader import response


def test_generated_interpretation_cannot_anchor_either_critic():
    packet, course, _, _ = example.__wrapped__()
    part = source_reader_parts(packet)[0]
    reading = response(packet, part)
    poison = 'UPSTREAM_MODEL_JUDGMENT_NOT_SOURCE_EVIDENCE'
    reading['source_notes'] = [{'note': poison, 'source_refs': [part.groups[0][1][0]]}]
    reading = validate_source_read(reading, packet, part)
    view = PracticalModelView(packet)
    for builder in (practical_review_messages, source_audit_messages):
        messages = builder(packet, course, model_view=view, source_readings=(reading,))
        encoded = json.dumps(messages)
        assert poison not in encoded
        assert 'SOURCE_BLOCK SRC1' in messages[1]['content']
    examiner = practical_review_messages(packet, course, model_view=view, source_readings=(reading,))
    assert 'correct_index' not in examiner[1]['content']
