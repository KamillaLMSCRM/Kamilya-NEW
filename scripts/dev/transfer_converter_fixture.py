"""Explicitly authorized, fixed-target temporary converter artifact transfer.

Uses the canonical proxy credentials, host-key policy and VM126 SSH route.
Does not execute arbitrary payloads or print source/converted document content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ops import kz_remote_exec as transport  # noqa: E402

REMOTE_DIR = "/home/kamilya-admin/incoming/semantic-pdf-20260918"
SOURCE_SHA = "a30c8f3dc158e2ca73a21535d3c28dddbf9f0a7778e417a91255c628dfd6e605"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("upload", "download", "cleanup"))
    parser.add_argument("--local", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.operation == "upload":
        if not args.local or hashlib.sha256(args.local.read_bytes()).hexdigest() != SOURCE_SHA:
            raise SystemExit("source_identity_mismatch")
    if args.operation == "download":
        if not args.local or args.local.exists():
            raise SystemExit("download_requires_new_local_path")
        if ROOT / "outputs" not in args.local.resolve().parents:
            raise SystemExit("download_outside_private_outputs")
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "operation": args.operation, "target": "vm126",
                          "remote_directory": REMOTE_DIR, "network_attempted": False}))
        return
    import paramiko
    transport.assert_canonical_trust_paths(transport.DEFAULT_ENV_FILE, transport.DEFAULT_KNOWN_HOSTS)
    host, username, password = transport.proxy_credentials(transport.DEFAULT_ENV_FILE)
    client = paramiko.SSHClient()
    client.load_host_keys(str(transport.DEFAULT_KNOWN_HOSTS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(host, username=username, password=password, allow_agent=False,
                       look_for_keys=False, timeout=30, auth_timeout=30, banner_timeout=30,
                       disabled_algorithms=transport.DISABLED_ALGORITHMS)
        identity = transport.run_channel(client, transport.VM126.command(30, "hostname"), b"", 40)
        if identity.exit_code or identity.stdout.strip() != b"kml":
            raise RuntimeError("target_identity_mismatch")
        channel = client.get_transport().open_session(timeout=30)
        argv = (*transport.VM126.remote_prefix[:-1], "-s", transport.VM126.remote_prefix[-1], "sftp")
        channel.exec_command(shlex.join(argv))
        channel.settimeout(60)
        with paramiko.SFTPClient(channel) as sftp:
            if args.operation == "upload":
                sftp.mkdir(REMOTE_DIR, mode=0o700)  # Existing directory fails closed.
                with sftp.open(REMOTE_DIR + "/source.pdf", "wx") as remote:
                    remote.write(args.local.read_bytes())
                sftp.chmod(REMOTE_DIR + "/source.pdf", 0o600)
            elif args.operation == "download":
                remote = REMOTE_DIR + "/result.json"
                if sftp.stat(remote).st_size > 8_000_000:
                    raise RuntimeError("result_size_limit")
                with sftp.open(remote, "rb") as stream:
                    content = stream.read()
                payload = json.loads(content)
                if payload.get("source_sha256") != SOURCE_SHA or not payload.get("converted", {}).get("markdown"):
                    raise RuntimeError("conversion_identity_or_content_invalid")
                args.local.parent.mkdir(parents=True, exist_ok=True)
                with args.local.open("xb") as destination:
                    destination.write(content)
                print(json.dumps({"result_sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}))
            else:
                names = set(sftp.listdir(REMOTE_DIR))
                if not names <= {"source.pdf", "result.json"}:
                    raise RuntimeError("unexpected_cleanup_entry")
                for name in sorted(names):
                    sftp.remove(REMOTE_DIR + "/" + name)
                sftp.rmdir(REMOTE_DIR)
        print(json.dumps({"status": "ok", "operation": args.operation, "target": "vm126"}))
    finally:
        client.close()


if __name__ == "__main__":
    main()
