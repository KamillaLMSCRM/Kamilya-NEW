import copy

import pytest

from scripts.deploy.verify_pinned_release_image import attestation, receipt

REPO = 'example/project'
SHA = 'a' * 40
IMAGE = 'ghcr.io/example/kamilya-api@sha256:' + 'b' * 64
RUN = {'id': 123, 'status': 'completed', 'conclusion': 'success', 'head_sha': SHA,
       'path': '.github/workflows/release-kz-production.yml', 'run_attempt': 1,
       'repository': {'full_name': REPO}, 'head_repository': {'full_name': REPO}}
RECORD = {'schema_version': 1, 'release_sha': SHA, 'product_version': '0.11.72',
          'image': IMAGE, 'ci_run_id': '55'}
ATTEST = [{'verificationResult': {'signature': {'certificate': {
    'githubWorkflowRepository': REPO, 'githubWorkflowSHA': SHA,
    'buildSignerURI': 'https://github.com/example/project/.github/workflows/release-kz-production.yml@refs/heads/dev'}},
    'statement': {'subject': [{'name': IMAGE.split('@')[0], 'digest': {'sha256': 'b' * 64}}],
                  'predicate': {'buildDefinition': {'externalParameters': {'workflow': {
                      'repository': 'https://github.com/example/project',
                      'path': '.github/workflows/release-kz-production.yml'}},
                      'resolvedDependencies': [{'digest': {'gitCommit': SHA}}]},
                      'runDetails': {'metadata': {'invocationId': 'https://github.com/example/project/actions/runs/123/attempts/1'}}}}}}]


def check(run=RUN, record=RECORD):
    return receipt(run, record, repo=REPO, sha=SHA, ci='55', build_id='123', version='0.11.72')


def test_receipt_exact_identity():
    assert check() == IMAGE


@pytest.mark.parametrize('field,value', [('head_sha', 'c' * 40), ('conclusion', 'failure'),
    ('path', '.github/workflows/other.yml'), ('repository', {'full_name': 'foreign/repo'}),
    ('head_repository', {'full_name': 'foreign/repo'})])
def test_reject_bad_build_run(field, value):
    run = copy.deepcopy(RUN)
    run[field] = value
    with pytest.raises(ValueError):
        check(run=run)


@pytest.mark.parametrize('field,value', [('ci_run_id', '56'), ('release_sha', 'c' * 40),
    ('image', 'ghcr.io/foreign/kamilya-api@sha256:' + 'b' * 64)])
def test_reject_bad_receipt(field, value):
    record = {**RECORD, field: value}
    with pytest.raises(ValueError):
        check(record=record)


def test_verified_attestation_is_bound_to_digest_run_and_source():
    attestation(ATTEST, repo=REPO, sha=SHA, build_id='123', image=IMAGE, attempt=1)
    with pytest.raises(ValueError):
        attestation([], repo=REPO, sha=SHA, build_id='123', image=IMAGE, attempt=1)
    with pytest.raises(ValueError):
        attestation(ATTEST, repo=REPO, sha=SHA, build_id='124', image=IMAGE, attempt=1)
    with pytest.raises(ValueError):
        attestation(ATTEST, repo=REPO, sha=SHA, build_id='123', image=IMAGE[:-1] + 'c', attempt=1)


def test_workflow_reuses_without_build_and_preserves_protected_execution():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / '.github/workflows/release-kz-production.yml').read_text()
    assert 'ref: ${{ github.workflow_sha }}' in text
    assert 'gh attestation verify "oci://${image}"' in text
    assert 'gh run download "${BUILD_RUN_ID}"' in text
    assert "name: Build and push immutable image\n        if: ${{ inputs.reuse_build_run_id == '' }}" in text
    assert 'environment: kz-production' in text
    assert 'sudo -n /usr/local/sbin/kamilya-release-runner execute' in text

@pytest.mark.parametrize('change', ['source', 'workflow', 'repository', 'attempt'])
def test_attestation_rejects_other_provenance(change):
    result = copy.deepcopy(ATTEST)
    verified = result[0]['verificationResult']
    if change == 'source':
        verified['signature']['certificate']['githubWorkflowSHA'] = 'c' * 40
    elif change == 'workflow':
        verified['statement']['predicate']['buildDefinition']['externalParameters']['workflow']['path'] = '.github/workflows/other.yml'
    elif change == 'repository':
        verified['signature']['certificate']['githubWorkflowRepository'] = 'foreign/repo'
    else:
        verified['statement']['predicate']['runDetails']['metadata']['invocationId'] += '0'
    with pytest.raises(ValueError):
        attestation(result, repo=REPO, sha=SHA, build_id='123', image=IMAGE, attempt=1)
