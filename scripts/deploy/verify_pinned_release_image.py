"""Verify a previously built release image before protected promotion.

Attestation input must be the successful output of gh attestation verify; parsing
this file alone does not perform cryptographic verification.
"""
import argparse
import json
import re
from pathlib import Path

WORKFLOW = '.github/workflows/release-kz-production.yml'


def receipt(run, record, *, repo, sha, ci, build_id, version):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('repository_invalid')
    if not re.fullmatch(r'[0-9a-f]{40}', sha) or not str(ci).isdigit() or not str(build_id).isdigit():
        raise ValueError('identity_invalid')
    if (str(run.get('id')) != str(build_id) or run.get('status') != 'completed'
            or run.get('conclusion') != 'success' or run.get('head_sha') != sha
            or run.get('path') != WORKFLOW or run.get('repository', {}).get('full_name') != repo
            or run.get('head_repository', {}).get('full_name') != repo):
        raise ValueError('build_run_invalid')
    image = record.get('image', '')
    expected = f'ghcr.io/{repo.split("/")[0].lower()}/kamilya-api@sha256:'
    if (set(record) != {'schema_version', 'release_sha', 'product_version', 'image', 'ci_run_id'}
            or record['schema_version'] != 1 or record['release_sha'] != sha
            or str(record['ci_run_id']) != str(ci) or record['product_version'] != version
            or not re.fullmatch(re.escape(expected) + r'[0-9a-f]{64}', image)):
        raise ValueError('image_receipt_invalid')
    return image


def attestation(results, *, repo, sha, build_id, image, attempt):
    if not isinstance(results, list) or not results:
        raise ValueError('attestation_missing')
    image_name, digest = image.split('@sha256:')
    expected_run = f'https://github.com/{repo}/actions/runs/{build_id}/attempts/{attempt}'
    expected_workflow = f'https://github.com/{repo}/{WORKFLOW}'
    for result in results:
        try:
            verified = result['verificationResult']
            identity = verified['signature']['certificate']
            stmt = verified['statement']
            definition = stmt['predicate']['buildDefinition']
            metadata = stmt['predicate']['runDetails']['metadata']
            workflow = definition['externalParameters']['workflow']
            deps = definition['resolvedDependencies']
            if (identity['githubWorkflowRepository'] == repo
                    and identity['githubWorkflowSHA'] == sha
                    and identity['buildSignerURI'].split('@', 1)[0] == expected_workflow
                    and workflow['repository'] == f'https://github.com/{repo}'
                    and workflow['path'] == WORKFLOW
                    and metadata['invocationId'] == expected_run
                    and any(d.get('digest', {}).get('gitCommit') == sha for d in deps)
                    and any(s.get('name') == image_name and s.get('digest', {}).get('sha256') == digest
                            for s in stmt['subject'])):
                return
        except (KeyError, TypeError, AttributeError):
            continue
    raise ValueError('attestation_identity_mismatch')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['receipt', 'attestation'])
    parser.add_argument('--dir', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--ci')
    parser.add_argument('--version')
    parser.add_argument('--image')
    args = parser.parse_args()
    directory = Path(args.dir)
    run = json.loads((directory / 'run.json').read_text(encoding='utf-8'))
    if args.mode == 'receipt':
        record = json.loads((directory / 'release-image.json').read_text(encoding='utf-8'))
        print(receipt(run, record, repo=args.repo, sha=args.sha, ci=args.ci,
                      build_id=args.run, version=args.version))
    else:
        results = json.loads((directory / 'attestation.json').read_text(encoding='utf-8'))
        attestation(results, repo=args.repo, sha=args.sha, build_id=args.run,
                    image=args.image, attempt=run['run_attempt'])


if __name__ == '__main__':
    main()
