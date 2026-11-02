#!/usr/bin/env bash
# kamilya-target: vm126
# kamilya-mode: mutation
# kamilya-correlation: DEV-WORKER-VM-VERIFY
# kamilya-output: sanitized
set -Eeuo pipefail
python3 - <<'PY'
"""Sanitized, fixed-container verification for the isolated VM126 DEV consumer."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
from pathlib import Path

CONTAINER = "kamilya-dev-worker"
NODE = "kamilya-dev-worker@vm126"
CELERY_COMMAND = ["celery", "-A", "app.core.celery_app:celery_app", "worker", "--loglevel=info", "--concurrency=1", "--queues=ai,documents,maintenance", "--hostname=" + NODE]
COMMAND = ["python", "/app/dev_private_model_runtime.py", *CELERY_COMMAND]
ROOT = Path("/opt/kamilya-dev-worker/releases")
EXPECTED_IDENTITY = None
RECEIVER_SHA = "a7470cca32295122245796acf17c9f8d6e3c7b904f417ac78b8ee069354b61ae"
RECEIVER_SHA_V3 = "5561169088dfdeade62f4566d468cfb0ae0d4587513138163efc892748db790a"
IMAGE_RE = re.compile(r"ghcr\.io/kamillalmscrm/kamilya-api@sha256:[0-9a-f]{64}")
HEALTH_CODE = r"""
from app.core.celery_app import celery_app
node="kamilya-dev-worker@vm126"
i=celery_app.control.inspect(destination=[node],timeout=5)
p=i.ping()
q=i.active_queues()
if not isinstance(p,dict) or set(p)!={node} or p[node]!={"ok":"pong"}: raise RuntimeError("ping_unverified")
if not isinstance(q,dict) or set(q)!={node} or {row["name"] for row in q[node]}!={"ai","documents","maintenance"}: raise RuntimeError("queues_unverified")
print("VM_DEV_CONSUMER_READY")
"""


def env_values(rows):
    if not isinstance(rows,list): raise ValueError("environment_shape")
    values={}
    for row in rows:
        if not isinstance(row,str) or "=" not in row: raise ValueError("environment_shape")
        key,value=row.split("=",1)
        if not key or key in values: raise ValueError("environment_duplicate")
        values[key]=value
    return values


def verify_container(row, staged, inherited):
    config,state,host=row.get("Config",{}),row.get("State",{}),row.get("HostConfig",{})
    image=config.get("Image")
    if not isinstance(image,str) or not IMAGE_RE.fullmatch(image): raise ValueError("image_invalid")
    if row.get("Name")!="/"+CONTAINER or state.get("Status")!="running" or state.get("Running") is not True: raise ValueError("identity_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}",str(row.get("Id",""))) or not state.get("StartedAt"): raise ValueError("boot_invalid")
    if config.get("Cmd")!=COMMAND or config.get("Entrypoint") not in (None,[]): raise ValueError("command_invalid")
    if config.get("Hostname")!=CONTAINER or config.get("User")!="10001:10001": raise ValueError("process_invalid")
    if env_values(config.get("Env")) != (inherited | staged): raise ValueError("environment_mismatch")
    if host.get("ReadonlyRootfs") is not True or host.get("Privileged") or host.get("CapAdd") or host.get("Devices"): raise ValueError("isolation_invalid")
    if host.get("CapDrop")!=["ALL"] or not set(host.get("SecurityOpt") or []) & {"no-new-privileges","no-new-privileges:true"}: raise ValueError("capabilities_invalid")
    if host.get("NanoCpus")!=1000000000 or host.get("Memory")!=1073741824: raise ValueError("resources_invalid")
    if host.get("NetworkMode")!="bridge" or set(row.get("NetworkSettings",{}).get("Networks",{}))!={"bridge"}: raise ValueError("network_invalid")
    if host.get("PortBindings") or config.get("ExposedPorts") and row.get("NetworkSettings",{}).get("Ports") and any(row["NetworkSettings"]["Ports"].values()): raise ValueError("ports_invalid")
    if row.get("Mounts") or host.get("Binds") or set(host.get("Tmpfs") or {})!={"/tmp"}: raise ValueError("mounts_invalid")
    return image,staged["RELEASE_SHA"]


def docker(*args, timeout=20):
    return subprocess.check_output(["docker",*args],stderr=subprocess.DEVNULL,timeout=timeout)


def inspect():
    rows=json.loads(docker("inspect",CONTAINER))
    if not isinstance(rows,list) or len(rows)!=1: raise ValueError("inspect_shape")
    return rows[0]


def secure_file(path, mode):
    for parent in (ROOT.parent,ROOT,ROOT/"env-v2",path.parent):
        info=parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700: raise ValueError("directory_unsafe")
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=mode or info.st_size>65536: raise ValueError("file_unsafe")
    return path.read_bytes()


def receiver_identity(staged, receiver_source):
    managed = staged.get("AI_MANAGED_LUNA_QA_DEV_ENABLED", "false") == "true"
    expected = RECEIVER_SHA_V3 if managed else RECEIVER_SHA
    if hashlib.sha256(receiver_source).hexdigest() != expected: raise ValueError("receiver_changed")
    return managed


def main():
    try:
        expected=EXPECTED_IDENTITY
        if not isinstance(expected,dict) or set(expected)!={"image","release_sha","environment_sha256"}: raise ValueError("expected_identity_missing")
        first=inspect()
        release=env_values(first.get("Config",{}).get("Env")).get("RELEASE_SHA","")
        if not re.fullmatch(r"[0-9a-f]{40}",release): raise ValueError("release_invalid")
        payload=secure_file(ROOT/"env-v2"/release/"runtime.env",0o600)
        env_sha=hashlib.sha256(payload).hexdigest()
        if env_sha != expected["environment_sha256"]: raise ValueError("expected_identity_mismatch")
        staged=env_values(payload.decode("utf-8").splitlines())
        managed=staged.get("AI_MANAGED_LUNA_QA_DEV_ENABLED", "false") == "true"
        receiver_path=ROOT/("vm126_dev_worker_env_receiver-v3.py" if managed else "vm126_dev_worker_env_receiver-v2.py")
        receiver_source=secure_file(receiver_path,0o600)
        receiver_identity(staged,receiver_source)
        spec=importlib.util.spec_from_file_location("owned_receiver",receiver_path)
        receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)
        receiver.validate_payload(payload,release,env_sha)
        if (staged.get("DEV_MODEL_SSH_ENABLED")!="true" or staged.get("DEV_OCR_SSH_ENABLED")!="true"
                or staged.get("DEV_MODEL_SSH_ROLE")!="worker" or not staged.get("DEV_MODEL_SSH_KEY_B64")
                or not staged.get("DEV_MODEL_SSH_KNOWN_HOST")): raise ValueError("private_supervisor_scope_invalid")
        image_rows=json.loads(docker("image","inspect",first["Image"]))
        if len(image_rows)!=1: raise ValueError("image_shape")
        inherited=env_values(image_rows[0].get("Config",{}).get("Env",[]))
        image,_=verify_container(first,staged,inherited)
        if (image,release,env_sha)!=(expected["image"],expected["release_sha"],expected["environment_sha256"]): raise ValueError("expected_identity_mismatch")
        if image not in image_rows[0].get("RepoDigests",[]): raise ValueError("image_digest_unverified")
        # The staged DEV database/broker and effective env are verified before ping.
        health=docker("exec",CONTAINER,"python","-c",HEALTH_CODE,timeout=20)
        if health.strip()!=b"VM_DEV_CONSUMER_READY": raise ValueError("consumer_not_ready")
        second=inspect();verify_container(second,staged,inherited)
        if any(second.get(k)!=first.get(k) for k in ("Id","Image")) or second["State"]["StartedAt"]!=first["State"]["StartedAt"]: raise ValueError("container_replaced")
        print(f"EVIDENCE|container={CONTAINER}|image={image}|release_sha={release}|env_sha256={env_sha}|container_id={first['Id']}|configuration=verified|consumer=ready|restarts={second.get('RestartCount',0)}")
        return 0
    except Exception:
        print("EVIDENCE|status=blocked|reason=vm_worker_runtime_unverified")
        return 1

if __name__=="__main__": raise SystemExit(main())

PY
