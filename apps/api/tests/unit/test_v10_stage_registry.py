"""V10 extends the frozen V9 stage registry with two owned post-editor roles."""
import pytest

from app.modules.ai.v3.normalized_editorial_review import normalized_review_format
from app.modules.ai.v3.practical_author_transport import is_practical_author_stage
from app.modules.ai.v3.practical_contract import _course_format, build_practical_source_packet
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V8_POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.simple_course_address_repair import address_repair_format
from app.modules.ai.v3.simple_course_block_editor import block_editor_format
from app.modules.ai.v3.simple_course_delta_editor import delta_editor_format
from app.modules.ai.v3.simple_course_service import simple_stage_allowed
from app.modules.ai.v3.simple_semantic_source_plan import semantic_plan_format
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus

V10 = 'v3-simple-unit-review-joint-post-card-editor-v10'
SOURCE, COURSE, REVIEW = 'a' * 64, 'b' * 64, 'c' * 64
OTHER = 'd' * 64


def review_format(source=SOURCE, course=COURSE):
    return normalized_review_format(['src-1'], ['lesson-1'], ['question-1'], source, course)


def repair_format(source=SOURCE, draft=COURSE):
    return block_editor_format(['src-1'], source, draft, ['BODY1'])


def review_group(source=SOURCE, course=COURSE):
    return f'practical:simple:review-bank:v10:{source}:unit={course}:output=32768'


def repair_group(source=SOURCE, course=COURSE, proposal=REVIEW):
    return f'practical:simple:repair-cards:v10:{source}:unit={course}:proposal={proposal}:output=32768'


def allowed(stage, group, fmt, policy=V10, validator=lambda x: x):
    return simple_stage_allowed(stage, group, fmt, policy=policy, validator=validator)


def test_v10_policy_constant_is_explicit():
    from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V10_POLICY
    assert SIMPLE_COURSE_REVIEW_V10_POLICY == V10


@pytest.mark.parametrize(('stage', 'group', 'fmt'), [
    ('review', review_group(), review_format()),
    ('repair', repair_group(), repair_format()),
])
def test_v10_registered_roles_are_owned_and_never_accepted_by_v9(stage, group, fmt):
    assert allowed(stage, group, fmt)
    assert is_practical_author_stage(stage, group)
    assert not allowed(stage, group, fmt, SIMPLE_COURSE_REVIEW_V9_POLICY)
    assert not allowed(stage, group, fmt, validator=None)


@pytest.mark.parametrize(('stage', 'group', 'fmt'), [
    ('repair', review_group(), review_format()),
    ('review', repair_group(), repair_format()),
    ('review', review_group(), repair_format()),
    ('repair', repair_group(), review_format()),
    ('review', review_group(source=OTHER), review_format()),
    ('review', review_group(course=OTHER), review_format()),
    ('review', review_group(), review_format(source=OTHER)),
    ('review', review_group(), review_format(course=OTHER)),
    ('repair', repair_group(source=OTHER), repair_format()),
    ('repair', repair_group(course=OTHER), repair_format()),
    ('repair', repair_group(), repair_format(source=OTHER)),
    ('repair', repair_group(), repair_format(draft=OTHER)),
    ('review', review_group().replace(':output=', f':proposal={REVIEW}:output='), review_format()),
    ('repair', repair_group().replace(f':proposal={REVIEW}', ''), repair_format()),
    ('repair', repair_group().replace(':output=', f':proposal={OTHER}:output='), repair_format()),
    ('review', review_group(source='g' * 64), review_format()),
    ('review', review_group(course='b' * 63), review_format()),
    ('repair', repair_group(proposal='c' * 63), repair_format()),
    ('repair', repair_group(proposal='C' * 64), repair_format()),
    ('review', review_group().replace('output=32768', 'output=oops'), review_format()),
    ('repair', repair_group().replace(':output=32768', ''), repair_format()),
    ('review', review_group().replace('review-bank', 'unknown-role'), review_format()),
])
def test_v10_rejects_wrong_stage_contract_or_identity(stage, group, fmt):
    assert not allowed(stage, group, fmt)


@pytest.mark.parametrize(('stage', 'group'), [
    ('repair', review_group()),
    ('review', repair_group()),
    ('review', review_group(source='g' * 64)),
    ('repair', repair_group(proposal='c' * 63)),
    ('repair', repair_group().replace(f':proposal={REVIEW}', '')),
    ('review', review_group().replace(':output=', f':proposal={REVIEW}:output=')),
    ('review', review_group().replace('review-bank', 'unknown-role')),
])
def test_v10_raw_custody_rejects_wrong_stage_or_malformed_role(stage, group):
    assert not is_practical_author_stage(stage, group)


def test_v10_reuses_each_registered_v9_child_not_v8_roles():
    corpus = synthetic_corpus('tenant-synthetic', mixed_origin=False)
    packet = build_practical_source_packet(corpus)
    source = packet.fingerprint
    plan_fmt = semantic_plan_format(packet, corpus)
    refs = [block.block_id for block in packet.blocks if block.text.strip()]
    unit_fmt = normalized_review_format(refs, ['lesson-1'], ['question-1'], source, COURSE)
    joint_fmt = block_editor_format(refs, source, COURSE, ['BODY1'])
    children = [
        ('review', f'practical:simple:plan:v9:{source}:output=32768', plan_fmt),
        ('lesson', f'practical:simple:author-unit:v9:{source}:plan={COURSE}:unit={REVIEW}:output=32768', _course_format(refs)),
        ('review', f'practical:simple:review-unit:v9:{source}:plan={COURSE}:unit={REVIEW}:output=32768', unit_fmt),
        ('review', f'practical:simple:review-content:v9:{source}:unit={COURSE}:output=32768', unit_fmt),
        ('repair', f'practical:simple:editor-joint:v9:{source}:unit={COURSE}:output=32768', joint_fmt),
        ('repair', f'practical:simple:repair-address:v9:{source}:unit={COURSE}:proposal={REVIEW}:output=32768',
         address_repair_format(source, COURSE, REVIEW, 1, ['BODY1'])),
    ]
    for stage, group, fmt in children:
        assert allowed(stage, group, fmt, SIMPLE_COURSE_REVIEW_V9_POLICY)
        assert allowed(stage, group, fmt)
    v8_group = f'practical:simple:editor-body:v8:{source}:unit={COURSE}:output=32768'
    v8_fmt = delta_editor_format(refs, source, COURSE)
    assert allowed('repair', v8_group, v8_fmt, SIMPLE_COURSE_REVIEW_V8_POLICY)
    assert not allowed('repair', v8_group, v8_fmt)
