import copy
from uuid import UUID

import pytest

from app.modules.ai.v3.practical_owned_media_aliases import canonicalize_owned_media, restore_owned_media

COURSE_ID = UUID('10000000-0000-4000-8000-000000000001')
OTHER_COURSE_ID = UUID('10000000-0000-4000-8000-000000000099')
LESSON_IDS = [UUID(f'20000000-0000-4000-8000-{index:012d}') for index in range(1, 6)]


def asset(index):
    return 'asset-' + format(index, '064x')


def image(lesson_index, asset_index, *, course=COURSE_ID, alt=None):
    label = alt if alt is not None else f'Figure {asset_index}'
    return f'![{label}](/v1/courses/{course}/lessons/{LESSON_IDS[lesson_index]}/source-assets/{asset(asset_index)})'


def snapshot():
    lessons = []
    index = 1
    for lesson_index, count in enumerate((3, 2, 3, 1, 1)):
        media = [image(lesson_index, number) for number in range(index, index + count)]
        lessons.append({'id': f'L{lesson_index + 1}', 'title': 'Title', 'content': '\n\n'.join(media),
                        'questions': [{'id': f'Q{lesson_index + 1}', 'text': 'unchanged'}]})
        index += count
    return {'title': 'Course', 'lessons': lessons}, {f'L{i + 1}': value for i, value in enumerate(LESSON_IDS)}


def adapted():
    course, owners = snapshot()
    canonical, manifest = canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)
    return course, canonical, manifest, owners


def test_ten_owned_images_round_trip_without_touching_snapshot():
    course, owners = snapshot()
    saved = copy.deepcopy(course)
    canonical, manifest = canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)
    assert course == saved
    assert sum(len(row['images']) for row in manifest['lessons']) == 10
    assert all('/v1/courses/' not in row['content'] for row in canonical['lessons'])
    restored, receipt = restore_owned_media(canonical, manifest)
    assert restored == saved and receipt['images_checked'] == 10 and receipt['aliases_restored'] == 10
    assert receipt['semantic_acceptance'] is False
    restored['lessons'][0]['questions'][0]['text'] = 'modified copy'
    assert course == saved


def test_canonical_and_opaque_images_remain_exact_while_prose_can_change():
    course, owners = snapshot()
    course['lessons'][0]['content'] += f'\n![Native](source-asset:{asset(101)})\n![External](https://example.org/a(b).png)'
    canonical, manifest = canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)
    assert f'![Native](source-asset:{asset(101)})' in canonical['lessons'][0]['content']
    assert '![External](https://example.org/a(b).png)' in canonical['lessons'][0]['content']
    canonical['lessons'][0]['content'] = 'Updated explanatory prose.\n' + canonical['lessons'][0]['content']
    restored, receipt = restore_owned_media(canonical, manifest)
    assert restored['lessons'][0]['content'] == 'Updated explanatory prose.\n' + course['lessons'][0]['content']
    assert receipt['images_checked'] == 12 and receipt['aliases_restored'] == 10


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'alt', 'order', 'wrong_lesson',
                                      'different_asset', 'foreign_same_asset', 'extra_canonical', 'external_change'])
def test_adversarial_model_media_is_rejected(mutation):
    course, canonical, manifest, _ = adapted()
    target = canonical['lessons'][0]['content']
    first = f'![Figure 1](source-asset:{asset(1)})'
    second = f'![Figure 2](source-asset:{asset(2)})'
    if mutation == 'missing':
        target = target.replace(first, '', 1)
    elif mutation == 'duplicate':
        target += '\n' + first
    elif mutation == 'alt':
        target = target.replace(first, f'![Changed](source-asset:{asset(1)})', 1)
    elif mutation == 'order':
        target = target.replace(first, 'TEMP_IMAGE', 1).replace(second, first, 1).replace('TEMP_IMAGE', second, 1)
    elif mutation == 'wrong_lesson':
        canonical['lessons'][0]['content'], canonical['lessons'][1]['content'] = (
            canonical['lessons'][1]['content'], canonical['lessons'][0]['content'])
        with pytest.raises(ValueError):
            restore_owned_media(canonical, manifest)
        return
    elif mutation == 'different_asset':
        target = target.replace(first, f'![Figure 1](source-asset:{asset(11)})', 1)
    elif mutation == 'foreign_same_asset':
        target = target.replace(first, image(0, 1, course=OTHER_COURSE_ID), 1)
    elif mutation == 'extra_canonical':
        target += f'\n![Extra](source-asset:{asset(99)})'
    else:
        course['lessons'][0]['content'] += '\n![Public](https://example.org/image.png)'
        canonical, manifest = canonicalize_owned_media(course, owned_course_id=COURSE_ID,
            owned_lesson_ids={f'L{i + 1}': value for i, value in enumerate(LESSON_IDS)})
        target = canonical['lessons'][0]['content'].replace('https://example.org/image.png', 'https://evil.example/image.png')
    canonical['lessons'][0]['content'] = target
    with pytest.raises(ValueError):
        restore_owned_media(canonical, manifest)


def test_foreign_owner_and_unsupported_indirect_images_fail_closed():
    course, owners = snapshot()
    course['lessons'][0]['content'] = image(0, 1, course=OTHER_COURSE_ID)
    with pytest.raises(ValueError, match='foreign_served'):
        canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)
    course['lessons'][0]['content'] = '![figure][ref]\n\n[ref]: https://example.org/figure.png'
    with pytest.raises(ValueError, match='reference_image_unsupported'):
        canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)
    course['lessons'][0]['content'] = '<img src="https://example.org/figure.png">'
    with pytest.raises(ValueError, match='html_image_unsupported'):
        canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)


def test_plain_asset_mentions_are_never_rewritten_or_expanded():
    course, owners = snapshot()
    mention = f'Plain source-asset:{asset(1)} remains plain.'
    course['lessons'][0]['content'] += '\n' + mention
    canonical, manifest = canonicalize_owned_media(course, owned_course_id=COURSE_ID, owned_lesson_ids=owners)
    assert mention in canonical['lessons'][0]['content']
    restored, _ = restore_owned_media(canonical, manifest)
    assert restored == course
    canonical['lessons'][0]['content'] += f'\nsource-asset:{asset(99)}'
    with pytest.raises(ValueError, match='plain_reference_changed'):
        restore_owned_media(canonical, manifest)
