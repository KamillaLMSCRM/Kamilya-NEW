"""Canonical CT137 SSH transport: no proxy storage or compute; exact native packet."""
import argparse
import json
import re
import shlex
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
parser.add_argument('--deploy', nargs=3, metavar=('RELEASE', 'PREVIOUS', 'DIGEST'))
args = parser.parse_args()
assert sum([bool(args.stage_file), args.status, args.test_helper, args.verify_boundary, bool(args.deploy)]) == 1
if args.stage_file:
    path = args.stage_file.resolve(strict=True)
    assert path.is_relative_to(ROOT)
    assert re.fullmatch(r'(frontend-native-[0-9a-f]{40}\.(tar\.gz|manifest\.json)|kamilya-web-deploy\.py|ct137-web-bootstrap\.sh)', path.name)
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
test -d /opt/kamilya-web/releases/e463527cd8f5e67e987c44d8d769f337714bd25f
printf 'ROLLBACK_RELEASE_PRESENT\n'
'''
        _, out, err = client.exec_command(transport.PREFIX + shlex.quote(command),timeout=30)
        output=out.read(4096).decode(); errors=err.read(4096)
        code=out.channel.recv_exit_status(); print(output)
        print(json.dumps({'boundary_exit':code,'stderr_bytes':len(errors)}))
        if code or errors: raise SystemExit(1)
    elif args.test_helper:
        helper = SOURCE_ROOT / 'infra/deploy/kamilya-web-deploy.py'
        tests = (SOURCE_ROOT / 'scripts/ops/test_kamilya_web_deploy.py').read_text(encoding='utf-8')
        tests = tests.replace('ROOT = Path(__file__).resolve().parents[2]', "ROOT = Path('/')")
        tests = tests.replace('ROOT / "infra/deploy/kamilya-web-deploy.py"', "Path('/home/kamilya-admin/incoming/kamilya-web-deploy.py')")
        probe = 'import hashlib, pathlib, os\nassert os.geteuid()!=0\nassert hashlib.sha256(pathlib.Path("/home/kamilya-admin/incoming/kamilya-web-deploy.py").read_bytes()).hexdigest() == ' + repr(transport.digest(helper)) + '\nexec(compile(' + repr(tests) + ',"ct137-helper-unit-tests","exec"))\n'
        stdin, out, err = client.exec_command(transport.PREFIX + shlex.quote('/usr/bin/python3 -I -'),timeout=90)
        stdin.write(probe); stdin.flush(); stdin.channel.shutdown_write()
        output = out.read(4096).decode(); errors = err.read(16384).decode()
        code = out.channel.recv_exit_status()
        print(output); print(errors); print(json.dumps({'native_test_exit':code}))
        if code: raise SystemExit(code)
    else:
        command = '/usr/bin/doas -n /usr/local/sbin/kamilya-web-deploy ' + ('status' if args.status else 'deploy ' + ' '.join(args.deploy))
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
