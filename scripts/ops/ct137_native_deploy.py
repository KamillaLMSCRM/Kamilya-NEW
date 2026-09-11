"""Canonical CT137 SSH transport: no proxy storage or compute; exact native packet."""
import argparse
import hashlib
import json
import re
import shlex
import tempfile
from pathlib import Path

ROOT = Path('C:/Kamilya New/Kamilya-NEW')
import ct137_ssh_transport as transport
SOURCE_ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--stage-file', type=Path)
parser.add_argument('--expected-sha256')
parser.add_argument('--status', action='store_true')
parser.add_argument('--test-helper', action='store_true')
parser.add_argument('--verify-boundary', action='store_true')
parser.add_argument('--expected-rollback-sha')
parser.add_argument('--deploy', nargs=3, metavar=('RELEASE', 'PREVIOUS', 'DIGEST'))
parser.add_argument('--cleanup-plan', nargs=3, metavar=('OBSOLETE', 'CURRENT', 'ROLLBACK'))
parser.add_argument('--cleanup', nargs=3, metavar=('OBSOLETE', 'CURRENT', 'ROLLBACK'))
parser.add_argument('--recovery-archive', type=Path)
parser.add_argument('--recovery-manifest', type=Path)
parser.add_argument('--prune-staged-copy', action='store_true')
args = parser.parse_args()
assert sum([bool(args.stage_file), args.status, args.test_helper, args.verify_boundary, bool(args.deploy), bool(args.cleanup_plan), bool(args.cleanup)]) == 1
if args.verify_boundary:
    assert re.fullmatch('[0-9a-f]{40}', args.expected_rollback_sha or '')
for operation in (args.cleanup_plan, args.cleanup):
    if operation:
        assert all(re.fullmatch('[0-9a-f]{40}', value) for value in operation[:3])
if args.cleanup:
    assert all(re.fullmatch('[0-9a-f]{40}', value) for value in args.cleanup)
    assert args.recovery_archive and args.recovery_manifest
else:
    assert not any((args.recovery_archive, args.recovery_manifest, args.prune_staged_copy))
if args.stage_file:
    path = args.stage_file.resolve(strict=True)
    assert path.is_relative_to(ROOT)
    assert re.fullmatch(r'(frontend-native-[0-9a-f]{40}\.(tar\.gz|manifest\.json)|cleanup-envelope-[0-9a-f]{64}\.json|kamilya-web-deploy(?:-[0-9a-f]{64})?\.py|ct137-web-(?:bootstrap|maintenance-update(?:-[0-9a-f]{64})?)\.sh)', path.name)
    assert re.fullmatch('[0-9a-f]{64}', args.expected_sha256 or '')
    assert transport.digest(path) == args.expected_sha256
    if path.suffix == '.gz':
        manifest = json.loads((path.parent / 'manifest.json').read_text())
        assert manifest['release_sha'] == path.name[16:-7]
        assert manifest['sha256'] == args.expected_sha256
        assert (manifest['platform'], manifest['arch'], manifest['libc'], manifest['api_url']) == ('linux', 'x64', 'musl', 'https://api.kml.kz/api')
if args.deploy:
    sha, previous, digest = args.deploy
    assert re.fullmatch('[0-9a-f]{40}', sha) and re.fullmatch('[0-9a-f]{40}', previous)
    assert re.fullmatch('[0-9a-f]{64}', digest)


def local_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_recovery(archive: Path, manifest: Path, obsolete: str | None = None) -> tuple[str, str]:
    archive = archive.resolve(strict=True)
    manifest = manifest.resolve(strict=True)
    if archive.name != f'frontend-native-{archive.name[16:-7]}.tar.gz' or not re.fullmatch('[0-9a-f]{40}', archive.name[16:-7]):
        raise SystemExit('BLOCKED: recovery archive is not SHA-scoped')
    release = archive.name[16:-7]
    if obsolete is not None and release != obsolete:
        raise SystemExit('BLOCKED: recovery archive release mismatch')
    if manifest.name != f'frontend-native-{release}.manifest.json':
        raise SystemExit('BLOCKED: recovery manifest is not SHA-scoped')
    archive_digest = local_digest(archive)
    manifest_digest = local_digest(manifest)
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    if payload.get('release_sha') != release or payload.get('sha256') != archive_digest:
        raise SystemExit('BLOCKED: recovery manifest does not bind the archive')
    return archive_digest, manifest_digest


values = transport.env()
assert values['PROXY_VPS_HOST'] == transport.PROXY
client = transport.paramiko.SSHClient()
client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
client.set_missing_host_key_policy(transport.paramiko.RejectPolicy())
try:
    client.connect(transport.PROXY, username=values['PROXY_VPS_LOGIN'], password=values['PROXY_VPS_PASSWORD'], allow_agent=False, look_for_keys=False, timeout=15)
    if args.stage_file:
        transport.stream(client, path)
    elif args.verify_boundary:
        command = '''set -eu
test "$(hostname)" = webkml
test "$(id -un)" = kamilya-admin
test "$(stat -c '%u:%g:%a' /usr/local/sbin/kamilya-web-deploy)" = 0:0:750
test "$(stat -c '%u:%g:%a' /opt/kamilya-web/releases)" = 0:0:755
if doas -n /usr/bin/id -u >/dev/null 2>&1; then printf 'BOUNDARY_FAIL unrestricted_root\n'; exit 1; fi
printf 'BOUNDARY_PASS restricted_helper_only\n'
printf 'NODE_VERSION='; node --version
printf 'FREE_KB='; df -Pk /opt/kamilya-web | awk 'NR==2 {print $4}'
test -d /opt/kamilya-web/releases/EXPECTED_ROLLBACK_SHA
printf 'ROLLBACK_RELEASE_PRESENT\n'
'''
        command = command.replace('EXPECTED_ROLLBACK_SHA', args.expected_rollback_sha)
        _, out, err = client.exec_command(transport.PREFIX + shlex.quote(command),timeout=30)
        output=out.read(4096).decode(); errors=err.read(4096)
        code=out.channel.recv_exit_status(); print(output)
        print(json.dumps({'boundary_exit':code,'stderr_bytes':len(errors)}))
        if code or errors: raise SystemExit(1)
    elif args.test_helper:
        helper = SOURCE_ROOT / 'infra/deploy/kamilya-web-deploy.py'
        helper_digest = transport.digest(helper)
        remote_helper = '/home/kamilya-admin/incoming/kamilya-web-deploy-' + helper_digest + '.py'
        probe = 'import hashlib,pathlib,os,types,sys,unittest\nassert os.geteuid()!=0\nassert hashlib.sha256(pathlib.Path(' + repr(remote_helper) + ').read_bytes()).hexdigest() == ' + repr(helper_digest) + '\nsuite=unittest.TestSuite()\n'
        for name in ('test_kamilya_web_deploy', 'test_kamilya_web_cleanup', 'test_kamilya_web_cleanup_controls'):
            tests = (SOURCE_ROOT / ('scripts/ops/' + name + '.py')).read_text(encoding='utf-8')
            tests = tests.replace('ROOT = Path(__file__).resolve().parents[2]', "ROOT = pathlib.Path('/')")
            tests = tests.replace('ROOT / "infra/deploy/kamilya-web-deploy.py"', 'Path(' + repr(remote_helper) + ')')
            # Keep source-contract reads bound to exactly the same staged helper.
            tests = tests.replace('(ROOT / "infra/deploy/kamilya-web-deploy.py")', 'Path(' + repr(remote_helper) + ')')
            probe += 'module=types.ModuleType(' + repr(name) + ');sys.modules[module.__name__]=module\nmodule.pathlib=pathlib\nexec(compile(' + repr(tests) + ',"ct137-helper-tests","exec"),module.__dict__)\nsuite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))\n'
        probe += 'result=unittest.TextTestRunner(verbosity=1).run(suite)\nraise SystemExit(not result.wasSuccessful())\n'
        stdin, out, err = client.exec_command(transport.PREFIX + shlex.quote('/usr/bin/python3 -I -'),timeout=90)
        stdin.write(probe); stdin.flush(); stdin.channel.shutdown_write()
        output = out.read(4096).decode(); errors = err.read(16384).decode()
        code = out.channel.recv_exit_status()
        print(output); print(errors); print(json.dumps({'native_test_exit':code}))
        if code: raise SystemExit(code)
    elif args.cleanup:
        obsolete, current, rollback = args.cleanup
        recovery_archive_digest, recovery_manifest_digest = validate_recovery(
            args.recovery_archive, args.recovery_manifest, obsolete
        )
        archive_name = f'frontend-native-{obsolete}.tar.gz'
        manifest_name = f'frontend-native-{obsolete}.manifest.json'
        staged_present = False
        if args.prune_staged_copy:
            staged_preflight = (
                "set -eu; cd /home/kamilya-admin/incoming; "
                f"if test -f {shlex.quote(archive_name)} && test -f {shlex.quote(manifest_name)}; then "
                f"test \"$(sha256sum {shlex.quote(archive_name)} | awk '{{print $1}}')\" = {recovery_archive_digest}; "
                f"test \"$(sha256sum {shlex.quote(manifest_name)} | awk '{{print $1}}')\" = {recovery_manifest_digest}; "
                "printf 'STAGED_PAIR_PRESENT\\n'; "
                f"elif test ! -e {shlex.quote(archive_name)} && test ! -e {shlex.quote(manifest_name)}; then "
                "printf 'STAGED_PAIR_ABSENT\\n'; else exit 1; fi"
            )
            _, staged_out, staged_err = client.exec_command(
                transport.PREFIX + shlex.quote(staged_preflight), timeout=240
            )
            staged_text = staged_out.read(128).decode('ascii', 'replace').strip()
            staged_errors = staged_err.read(4096)
            staged_code = staged_out.channel.recv_exit_status()
            if staged_code or staged_errors or staged_text not in ('STAGED_PAIR_PRESENT', 'STAGED_PAIR_ABSENT'):
                raise SystemExit('BLOCKED: staged cleanup preflight failed')
            staged_present = staged_text == 'STAGED_PAIR_PRESENT'
        plan_command = '/usr/bin/doas -n /usr/local/sbin/kamilya-web-deploy cleanup-plan ' + ' '.join((obsolete, current, rollback))
        _, plan_out, plan_err = client.exec_command(transport.PREFIX + shlex.quote(plan_command), timeout=240)
        plan_text = plan_out.read(16384).decode('utf-8', 'replace')
        plan_errors = plan_err.read(4096)
        plan_code = plan_out.channel.recv_exit_status()
        if plan_code or plan_errors:
            raise SystemExit('BLOCKED: cleanup plan failed')
        plan = json.loads(plan_text)
        if (plan.get('release_sha'), plan.get('current_sha'), plan.get('rollback_sha')) != (obsolete, current, rollback):
            raise SystemExit('BLOCKED: cleanup plan identity mismatch')
        envelope = {**plan, 'recovery_archive_sha256': recovery_archive_digest,
                    'recovery_manifest_sha256': recovery_manifest_digest}
        content = (json.dumps(envelope, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        envelope_digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory(prefix='kamilya-ct137-cleanup-') as temp_dir:
            local_envelope = Path(temp_dir) / f'cleanup-envelope-{envelope_digest}.json'
            local_envelope.write_bytes(content)
            transport.stream(client, local_envelope)
        cleanup_command = '/usr/bin/doas -n /usr/local/sbin/kamilya-web-deploy cleanup ' + envelope_digest
        _, cleanup_out, cleanup_err = client.exec_command(transport.PREFIX + shlex.quote(cleanup_command), timeout=240)
        cleanup_text = cleanup_out.read(16384).decode('utf-8', 'replace')
        cleanup_errors = cleanup_err.read(4096)
        cleanup_code = cleanup_out.channel.recv_exit_status()
        if cleanup_code or cleanup_errors:
            raise SystemExit('BLOCKED: cleanup helper failed')
        result = json.loads(cleanup_text)
        expected_result = {
            **plan,
            'status': 'CLEANED',
            'envelope_sha256': envelope_digest,
            'recovery_archive_sha256': recovery_archive_digest,
            'recovery_manifest_sha256': recovery_manifest_digest,
        }
        if any(result.get(key) != value for key, value in expected_result.items()):
            raise SystemExit('BLOCKED: cleanup did not complete')
        envelope_name = f'cleanup-envelope-{envelope_digest}.json'
        cleanup_parts = [
            'set -eu',
            'cd /home/kamilya-admin/incoming',
            f"test \"$(sha256sum {shlex.quote(envelope_name)} | awk '{{print $1}}')\" = {envelope_digest}",
            f"rm -f -- {shlex.quote(envelope_name)}",
        ]
        if staged_present:
            cleanup_parts.extend([
                f"test \"$(sha256sum {shlex.quote(archive_name)} | awk '{{print $1}}')\" = {recovery_archive_digest}",
                f"test \"$(sha256sum {shlex.quote(manifest_name)} | awk '{{print $1}}')\" = {recovery_manifest_digest}",
                f"rm -f -- {shlex.quote(archive_name)} {shlex.quote(manifest_name)}",
            ])
        cleanup_parts.append("printf 'USER_STAGING_CLEANED\\n'")
        _, files_out, files_err = client.exec_command(
            transport.PREFIX + shlex.quote('; '.join(cleanup_parts)), timeout=240
        )
        files_text = files_out.read(128).decode('ascii', 'replace').strip()
        files_errors = files_err.read(4096)
        files_code = files_out.channel.recv_exit_status()
        staging_cleanup_ok = not files_code and not files_errors and files_text == 'USER_STAGING_CLEANED'
        print(json.dumps({'status': 'CLEANUP_OK', 'envelope_sha256': envelope_digest,
                          'release_sha': obsolete, 'current_sha': current,
                          'rollback_sha': rollback, 'tree_sha256': plan['tree_sha256'],
                          'recovery_archive_sha256': recovery_archive_digest,
                          'recovery_manifest_sha256': recovery_manifest_digest,
                          'staged_artifacts_removed': staged_present and staging_cleanup_ok,
                          'staging_cleanup_ok': staging_cleanup_ok}, sort_keys=True))
    else:
        operation = ('status' if args.status else 'cleanup-plan ' + ' '.join(args.cleanup_plan) if args.cleanup_plan
                     else 'deploy ' + ' '.join(args.deploy))
        command = '/usr/bin/doas -n /usr/local/sbin/kamilya-web-deploy ' + operation
        _, out, err = client.exec_command(transport.PREFIX + shlex.quote(command), timeout=240)
        output = out.read(16384).decode('utf-8', 'replace')
        errors = err.read(4096)
        code = out.channel.recv_exit_status()
        print(output)
        if errors:
            try:
                error_data = json.loads(errors)
                if error_data.get('status') == 'BLOCKED' and re.fullmatch('[a-z0-9_]+',error_data.get('reason','')):
                    print(json.dumps(error_data))
            except (ValueError,TypeError):
                pass
        print(json.dumps({'exit_code':code,'stderr_bytes':len(errors)}))
        if code:
            raise SystemExit(code)
finally:
    client.close()
