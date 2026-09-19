#!/usr/bin/env bash
# kamilya-target: vm126
# kamilya-mode: mutation
# kamilya-correlation: semantic-pdf-20260918
# kamilya-output: sanitized
set -Eeuo pipefail
phase=preflight
trap 'printf "EVIDENCE|failed_phase=%s|exit_code=%s\n" "$phase" "$?"' ERR
test "$(hostname)" = kml
source_file=/home/kamilya-admin/incoming/semantic-pdf-20260918/source.pdf
result_file=/home/kamilya-admin/incoming/semantic-pdf-20260918/result.json
test ! -e "$result_file"
printf 'a30c8f3dc158e2ca73a21535d3c28dddbf9f0a7778e417a91255c628dfd6e605  %s\n' "$source_file" | sha256sum --check --status
slot="$(python3 -c 'import json; print(json.load(open("/var/lib/kamilya-release-plane/state.json"))["active_slot"])')"
case "$slot" in blue|green) ;; *) exit 1 ;; esac
container="kamilya-$slot-api-1"
docker inspect "$container" >/dev/null
printf 'EVIDENCE|active_slot=%s\n' "$slot"
cleanup() {
  docker exec --user 0 "$container" rm -f /tmp/semantic-pdf-20260918.pdf /tmp/semantic-pdf-20260918.json
}
trap cleanup EXIT
phase=temporary_result_absence
docker exec "$container" test ! -e /tmp/semantic-pdf-20260918.json
phase=temporary_input_identity
if docker exec --user 0 "$container" test -e /tmp/semantic-pdf-20260918.pdf; then
  docker exec --user 0 "$container" python -c 'import hashlib; assert hashlib.sha256(open("/tmp/semantic-pdf-20260918.pdf", "rb").read()).hexdigest() == "a30c8f3dc158e2ca73a21535d3c28dddbf9f0a7778e417a91255c628dfd6e605"'
else
  phase=temporary_input_copy
  docker exec -i "$container" python -c 'import hashlib,pathlib,sys; data=sys.stdin.buffer.read(); assert hashlib.sha256(data).hexdigest()=="a30c8f3dc158e2ca73a21535d3c28dddbf9f0a7778e417a91255c628dfd6e605"; p=pathlib.Path("/tmp/semantic-pdf-20260918.pdf"); p.open("xb").write(data); p.chmod(0o400)' < "$source_file"
fi
phase=conversion
docker exec -i "$container" python - <<'PY'
import asyncio, hashlib, json, time
from pathlib import Path
from app.modules.ai.ingestion import DocumentConverter
source = Path('/tmp/semantic-pdf-20260918.pdf')
started = time.perf_counter()
converted = asyncio.run(asyncio.wait_for(DocumentConverter().convert(str(source)), timeout=265))
assert converted.get('markdown', '').strip(), 'empty_converter_result'
payload = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
           'source_bytes': source.stat().st_size, 'seconds': time.perf_counter()-started,
           'capture_mode': 'deployed_application_converter', 'converted': converted}
Path('/tmp/semantic-pdf-20260918.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
print('EVIDENCE|conversion=complete|source=sha256_verified')
PY
phase=result_copy
python3 - "$container" "$result_file" <<'PY'
import json, subprocess, sys
from pathlib import Path
data = subprocess.check_output(['docker', 'exec', sys.argv[1], 'python', '-c',
    'import sys; sys.stdout.buffer.write(open("/tmp/semantic-pdf-20260918.json","rb").read())'])
assert len(data) < 8_000_000
result = json.loads(data)
assert result['source_sha256'] == 'a30c8f3dc158e2ca73a21535d3c28dddbf9f0a7778e417a91255c628dfd6e605'
assert result['converted']['markdown'].strip()
with Path(sys.argv[2]).open('xb') as destination:
    destination.write(data)
PY
chown kamilya-admin:kamilya-admin "$result_file"
chmod 600 "$result_file"
printf 'EVIDENCE|result=private_artifact_ready\n'
