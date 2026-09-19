#!/usr/bin/env bash
# kamilya-target: vm126
# kamilya-mode: mutation
# kamilya-correlation: semantic-pdf-20260918
# kamilya-output: sanitized
set -Eeuo pipefail
# Elevated inspection only, within the authorized converter capture operation.
python3 - <<'PY'
import hashlib, json, subprocess, urllib.request
from pathlib import Path
source = Path('/home/kamilya-admin/incoming/semantic-pdf-20260918/source.pdf')
print('EVIDENCE|source_sha256=' + hashlib.sha256(source.read_bytes()).hexdigest())
health = json.load(urllib.request.urlopen('http://10.77.77.2:8000/health', timeout=10))
for key in ('version', 'git_sha', 'release_sha', 'commit'):
    value = health.get(key)
    if isinstance(value, str) and all(c.isalnum() or c in '.-_' for c in value):
        print('EVIDENCE|health_field=' + key + '|value=' + value)
ids = subprocess.check_output(['docker', 'ps', '-q'], text=True).split()
for cid in ids:
    info = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
    name = info['Name'].lstrip('/')
    if 'kamilya' in name and ('api' in name or 'docling' in name):
        print('EVIDENCE|container=' + name + '|image_id=' + info['Image'].replace(':', '-'))
        labels = info['Config'].get('Labels') or {}
        revision = labels.get('org.opencontainers.image.revision', '')
        if revision and all(c in '0123456789abcdef' for c in revision):
            print('EVIDENCE|container=' + name + '|revision=' + revision)
active = json.loads(Path('/var/lib/kamilya-release-plane/state.json').read_text())['active_slot']
assert active in ('blue', 'green')
container = 'kamilya-' + active + '-api-1'
probe = subprocess.run(['docker', 'exec', '--user', '0', container, 'python', '-c',
    'import pathlib; p=pathlib.Path("/tmp/semantic-pdf-20260918.pdf"); r=pathlib.Path("/tmp/semantic-pdf-20260918.json"); print("EVIDENCE|input_exists="+str(int(p.exists()))+"|output_exists="+str(int(r.exists())))'], capture_output=True, text=True)
print('EVIDENCE|exec_probe_exit=' + str(probe.returncode))
if probe.returncode == 0:
    print(probe.stdout.strip())
else:
    message = (probe.stdout + probe.stderr).lower()
    for marker in ('read-only', 'permission denied', 'executable file not found', 'not running', 'no such file'):
        if marker in message:
            print('EVIDENCE|exec_error_class=' + marker.replace(' ', '_'))
for label, command in (
    ('test_absent', ['docker', 'exec', container, 'test', '!', '-e', '/tmp/semantic-pdf-20260918.json']),
    ('uid', ['docker', 'exec', container, 'id', '-u']),
):
    result = subprocess.run(command, capture_output=True, text=True)
    print('EVIDENCE|probe=' + label + '|exit=' + str(result.returncode))
    for marker in ('read-only', 'permission denied', 'executable file not found', 'not running', 'no such file', 'not found'):
        if marker in (result.stdout + result.stderr).lower():
            print('EVIDENCE|probe=' + label + '|error_class=' + marker.replace(' ', '_'))
PY
