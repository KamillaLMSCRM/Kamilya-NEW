"""Temporary DEV-only ASUS reverse stream via the canonical Windows SSH route.

Network-free plan first; execute only with its exact digest. No public listener,
credential copying, provider fallback, reconnect, or persisted remote service.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ops import kz_remote_exec as transport
from scripts.ops import reverse_model_stream as relay


class ChannelWriter:
    """Paramiko's file.write returns None; the binary relay needs byte counts."""
    def __init__(self, channel):
        self.channel = channel

    def write(self, data):
        self.channel.sendall(data)
        return len(data)

    def flush(self):
        pass


def payload(plan, nonce):
    source = (ROOT / 'scripts/ops/reverse_model_stream.py').read_bytes()
    guard = (
        "import os,sys\n"
        "assert os.getenv('DEPLOYMENT_ENVIRONMENT') == 'vm-development-worker', 'wrong_environment'\n"
        "assert os.getenv('RELEASE_SHA') == " + repr(plan['release']) + ", 'wrong_release'\n"
    )
    # Keep the imported module's CLI inactive, then call its bounded API.
    module = "import types\nm=types.ModuleType('dev_reverse_stream')\n"
    module += "exec(" + repr(source.decode('utf-8')) + ",m.__dict__)\n"
    return (guard + module + "m.remote_server(sys.stdin.buffer,sys.stdout.buffer,session_nonce="
            + repr(nonce) + ",lifetime_seconds=" + str(plan['lifetime_seconds']) + ")\n").encode()


def remote_command(*argv):
    # Same two-level quotation as run_with_vm126_docling_tunnel.py.
    return shlex.join((*transport.VM126.remote_prefix, *argv))


def python_command(container, code, *, lifetime=40):
    bootstrap = "import base64;exec(base64.b64decode(" + repr(base64.b64encode(code).decode()) + "))"
    return remote_command('timeout', '--signal=TERM', '--kill-after=5s', f'{lifetime}s',
                          'sudo', '-n', 'docker', 'exec', '-i', container,
                          'python', '-u', '-c', shlex.quote(bootstrap))


def checked_run(client, command):
    result = transport.run_channel(client, command, b'', 45)
    if result.exit_code != 0:
        terminal = result.stderr.decode('utf-8', errors='replace').splitlines()[-1:]
        name = terminal[0].split(':', 1)[0] if terminal else 'unknown'
        if not re.fullmatch('[A-Za-z_.]{1,80}', name):
            name = 'unknown'
        raise RuntimeError(f'bridge_readback_failed:exit={result.exit_code}:class={name}')
    return result.stdout.decode('utf-8').strip()


def plan_for(args):
    if not re.fullmatch('[0-9a-f]{64}', args.container) or not re.fullmatch(
            'ghcr.io/kamillalmscrm/kamilya-api@sha256:[0-9a-f]{64}', args.image):
        raise ValueError('exact_container_and_image_required')
    if not re.fullmatch('[0-9a-f]{40}', args.release):
        raise ValueError('exact_release_required')
    if not 1 <= args.lifetime <= 7200:
        raise ValueError('invalid_lifetime')
    plan = {'container': args.container, 'image': args.image, 'release': args.release,
            'lifetime_seconds': args.lifetime, 'probe_only': args.probe_only,
            'inference_probe': getattr(args, 'inference_probe', False),
            'listen': relay.LISTEN, 'upstream': relay.UPSTREAM,
            'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'relay_sha256': hashlib.sha256((ROOT / 'scripts/ops/reverse_model_stream.py').read_bytes()).hexdigest()}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan, digest


def execute(plan, receipt_path=None):
    import paramiko

    transport.assert_canonical_trust_paths(transport.DEFAULT_ENV_FILE, transport.DEFAULT_KNOWN_HOSTS)
    host, username, password = transport.proxy_credentials(transport.DEFAULT_ENV_FILE)
    client = paramiko.SSHClient()
    client.load_host_keys(str(transport.DEFAULT_KNOWN_HOSTS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    channel = None
    worker = None
    errors = []
    timer = None
    try:
        client.connect(host, username=username, password=password, allow_agent=False,
                       look_for_keys=False, timeout=30, auth_timeout=30, banner_timeout=30,
                       disabled_algorithms=transport.DISABLED_ALGORITHMS)
        guest = checked_run(client, transport.VM126.command(30, 'hostname'))
        if guest.casefold() != transport.VM126.expected_hostname.casefold():
            raise RuntimeError('bridge_guest_mismatch')
        identity = checked_run(client, remote_command('sudo', '-n', 'docker', 'inspect',
            '--format', shlex.quote('{{.Id}}|{{.Config.Image}}|{{.State.Running}}'), 'kamilya-dev-worker'))
        if identity != f"{plan['container']}|{plan['image']}|true":
            raise RuntimeError('bridge_worker_identity_mismatch')
        nonce = uuid.uuid4().hex
        channel = client.get_transport().open_session(timeout=30)
        channel.exec_command(python_command(plan['container'], payload(plan, nonce),
                                           lifetime=plan['lifetime_seconds'] + 5))
        timer = threading.Timer(plan['lifetime_seconds'], client.close)
        timer.daemon = True
        timer.start()
        def run():
            try:
                relay.local_client(channel.makefile('rb'), ChannelWriter(channel),
                                   expected_nonce=nonce, lifetime_seconds=plan['lifetime_seconds'])
            except Exception as exc:
                errors.append(type(exc).__name__)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        # One bounded metadata probe; no generation or repeated model request.
        probe = b'''import json,time,urllib.request
start=time.monotonic()
url='http://127.0.0.1:18890/v1/models'
for attempt in range(20):
    try:
        with urllib.request.urlopen(url,timeout=10) as r: data=json.load(r)
        break
    except ConnectionRefusedError:
        time.sleep(.1)
    except urllib.error.URLError as e:
        if not isinstance(e.reason,ConnectionRefusedError): raise
        time.sleep(.1)
else: raise RuntimeError('listener_not_ready')
models=[x.get('id') for x in data.get('data',[])]
assert 'DeepSeek-V4.1-Flash-1017' in models, 'model_mismatch'
print(json.dumps({'status':'ready','model':'DeepSeek-V4.1-Flash-1017','seconds':round(time.monotonic()-start,3)}))
'''
        try:
            print(checked_run(client, python_command(plan['container'], probe)), flush=True)
        except RuntimeError:
            if errors:
                print(json.dumps({'status':'local_stream_failed','class':errors[0]}), flush=True)
            if channel.recv_stderr_ready():
                diagnostic = channel.recv_stderr(65536).decode('utf-8', errors='replace')
                known = next((code for code in ('wrong_environment', 'wrong_release', 'Address already in use',
                                                'SyntaxError', 'ProtocolError') if code in diagnostic), 'unknown')
                print(json.dumps({'status':'remote_stream_failed','reason':known}), flush=True)
            raise
        if plan['inference_probe']:
            inference = b'''import json,time,urllib.request
start=time.monotonic()
data={'model':'DeepSeek-V4.1-Flash-1017','messages':[{'role':'user','content':
'Check these synthetic quiz keys. Q1: 2+2=? choices [3,4,5,6], key 0. Q2: 3+3=? choices [6,7,8,9], key 0. Return only JSON with q1_correct_index and q2_correct_index.'}],
'max_tokens':1024,'temperature':0,'reasoning_effort':'low','thinking_budget':256,
'chat_template_kwargs':{'enable_thinking':True}}
request=urllib.request.Request('http://127.0.0.1:18890/v1/chat/completions',
    data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=45) as r: response=json.load(r)
choice=response['choices'][0]; message=choice['message']; content=message.get('content','')
value=json.loads(content)
assert value=={'q1_correct_index':1,'q2_correct_index':0}, 'synthetic_key_mismatch'
assert choice.get('finish_reason')=='stop', 'incomplete_response'
assert response.get('model')=='DeepSeek-V4.1-Flash-1017', 'model_mismatch'
usage=response.get('usage',{})
print(json.dumps({'status':'inference_pass','model':response['model'],
'seconds':round(time.monotonic()-start,3),'prompt_tokens':usage.get('prompt_tokens'),
'completion_tokens':usage.get('completion_tokens'),'reasoning_enabled':True,
'thinking_budget':256,'corrected_bad_key':True,'retained_good_key':True}))
'''
            value = json.loads(checked_run(client, python_command(plan['container'], inference, lifetime=50)))
            with receipt_path.open('x', encoding='utf-8') as stream:
                json.dump({'plan':plan,'result':value}, stream, indent=2)
            print(json.dumps(value), flush=True)
        if not plan['probe_only']:
            while worker.is_alive() and not errors:
                worker.join(1)
        if errors:
            raise RuntimeError('bridge_stream_failed:' + errors[0])
        if plan['probe_only']:
            channel.close()
            worker.join(5)
            closed = b'''import socket,time,json
for attempt in range(20):
    with socket.socket() as s:
        s.settimeout(.2)
        if s.connect_ex(('127.0.0.1',18890)) != 0: break
    time.sleep(.1)
else: raise RuntimeError('listener_cleanup_failed')
print(json.dumps({'status':'closed','listener_remaining':False}))
'''
            print(checked_run(client, python_command(plan['container'], closed)), flush=True)
    finally:
        if timer:
            timer.cancel()
        if channel:
            channel.close()
        client.close()
        if worker:
            worker.join(5)
            if worker.is_alive():
                raise RuntimeError('bridge_local_cleanup_timeout')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--container', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--lifetime', type=int, default=7200)
    parser.add_argument('--probe-only', action='store_true')
    parser.add_argument('--inference-probe', action='store_true')
    parser.add_argument('--receipt-path', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    plan, digest = plan_for(args)
    if not args.execute:
        print(json.dumps({'status':'dry_run','sha256':digest,**plan}, sort_keys=True))
        return
    if args.expected_sha256 != digest:
        raise RuntimeError('bridge_plan_changed')
    if args.inference_probe:
        if not args.probe_only or args.receipt_path is None or args.lifetime < 60:
            raise ValueError('inference_probe_scope_invalid')
        intent = args.receipt_path.with_suffix('.intent.json')
        with intent.open('x', encoding='utf-8') as stream:
            json.dump({'plan':plan,'sha256':digest}, stream, indent=2)
    execute(plan, args.receipt_path)


if __name__ == '__main__':
    main()
