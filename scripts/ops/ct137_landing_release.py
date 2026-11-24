"""Release the exact approved landing source to CT137 with off-host archival."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

from ct137_archive_store import (
    DIGEST, SHA, ArchiveError, command, file_hash, publish_package, read_settings, ssh_client,
)
import ct137_ssh_transport as transport

LANDING_ROOT = transport.ROOT / "kamilya-landing"
REPOSITORY = "KamillaLMSCRM/kamilya-landing"
HELPER = "/usr/local/sbin/kamilya-landing-deploy"
MARKER = "/etc/kamilya-landing-release"
PUBLIC_ORIGIN = "https://www.kml.kz"


def local(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ArchiveError("landing_local_gate_failed")
    return result.stdout.strip()


def require_source(repo: Path, sha: str, previous: str, helper_digest: str, preview: dict) -> None:
    if not SHA.fullmatch(sha) or not SHA.fullmatch(previous) or sha == previous or not DIGEST.fullmatch(helper_digest):
        raise ArchiveError("landing_release_identity_invalid")
    if not repo.is_relative_to(LANDING_ROOT) or repo == LANDING_ROOT:
        raise ArchiveError("landing_release_worktree_required")
    common_git_dir = local(repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir")
    if Path(common_git_dir).resolve() != (LANDING_ROOT / ".git").resolve():
        raise ArchiveError("landing_release_worktree_invalid")
    if local(repo, "git", "rev-parse", "HEAD") != sha or local(repo, "git", "status", "--porcelain"):
        raise ArchiveError("landing_release_worktree_dirty_or_wrong_sha")
    if (preview.get("status"), preview.get("phase"), preview.get("release_sha")) != ("PASS", "preview", sha):
        raise ArchiveError("landing_preview_receipt_identity_mismatch")
    checks = {(row["width"], row["lang"]) for row in preview["checks"]}
    if not checks >= {(width, lang) for width in (390, 768, 1440) for lang in ("ru", "kk")}:
        raise ArchiveError("landing_preview_coverage_incomplete")
    settings = read_settings(LANDING_ROOT / ".env.local")
    env = {
        **os.environ, "GH_TOKEN": settings["github_landing_token"], "GIT_TERMINAL_PROMPT": "0",
        "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1",
    }
    account = local(repo, "gh", "api", "user", "--jq", ".login", env=env)
    master = local(repo, "gh", "api", f"repos/{REPOSITORY}/git/ref/heads/master", "--jq", ".object.sha", env=env)
    if (account, master) != ("KamillaLMSCRM", sha):
        raise ArchiveError("landing_protected_master_mismatch")


def make_archive(repo: Path, sha: str, directory: Path) -> dict[str, tuple[Path, str]]:
    source = directory / "source.tar.gz"
    checksum = directory / "source.sha256"
    paths = [name for name in local(repo, "git", "ls-tree", "--name-only", sha).splitlines()
             if name not in {"marketing", ".env.example"}]
    local(repo, "git", "archive", "--format=tar.gz", f"--output={source}", sha, "--", *paths)
    with tarfile.open(source) as archive:
        if archive.pax_headers.get("comment") != sha:
            raise ArchiveError("landing_archive_revision_mismatch")
        for member in archive:
            path = PurePosixPath(member.name)
            if (not (member.isfile() or member.isdir()) or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or any(part.startswith(".env") for part in path.parts)):
                raise ArchiveError("landing_archive_entry_invalid")
    digest = file_hash(source)
    checksum.write_bytes(f"{digest}  source.tar.gz\n".encode("ascii"))
    return {source.name: (source, digest), checksum.name: (checksum, file_hash(checksum))}


def execute(client, sha: str, previous: str, helper_digest: str, files: dict, publish=publish_package) -> dict:
    def remote(script: str, timeout: int = 90) -> str:
        return command(client, transport.PREFIX + shlex.quote(script), timeout)

    preflight = f"""set -eu
test "$(hostname)" = webkml
test "$(id -un)" = kamilya-admin
test "$(cat {MARKER})" = {previous}
test "$(readlink -f /opt/kamilya-landing/current)" = /opt/kamilya-landing/releases/{previous}
test "$(sha256sum {HELPER} | cut -d ' ' -f 1)" = {helper_digest}
rc-service kamilya-landing status >/dev/null
"""
    incoming_free = f"test ! -e {transport.INCOMING}/source.tar.gz\n"
    remote(preflight + incoming_free)
    receipt = publish("landing", sha, files)
    remote(preflight + incoming_free)
    source, digest = files["source.tar.gz"]
    transport.stream(client, source)
    deployed = remote(preflight + f"doas -n {HELPER} deploy {sha} {digest}", timeout=1800)
    if f"DEPLOY_OK release={sha} digest={digest}" not in deployed.splitlines():
        raise ArchiveError("landing_helper_readback_mismatch")
    remote(f"""set -eu
test "$(cat {MARKER})" = {sha}
test "$(readlink -f /opt/kamilya-landing/current)" = /opt/kamilya-landing/releases/{sha}
test -d /opt/kamilya-landing/releases/{previous}
test ! -e {transport.INCOMING}/source.tar.gz
rc-service kamilya-landing status >/dev/null
""")
    for path in ("/ru", "/kk"):
        with urllib.request.urlopen(f"{PUBLIC_ORIGIN}{path}", timeout=20) as response:
            if response.status != 200 or response.headers.get("X-Kamilya-Landing-Release") != sha:
                raise ArchiveError("landing_public_revision_mismatch")
    return {"status": "RELEASE_OK", "release_sha": sha, "rollback_sha": previous, "offhost_archive": receipt}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--preview-receipt", type=Path, required=True)
    parser.add_argument("--preview-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        if file_hash(args.preview_receipt) != args.preview_sha256:
            raise ArchiveError("landing_preview_receipt_checksum_mismatch")
        repo = args.repo.resolve(strict=True)
        preview = json.loads(args.preview_receipt.read_text(encoding="utf-8-sig"))
        require_source(repo, args.sha, args.previous, args.helper_sha256, preview)
        evidence = args.evidence.resolve()
        evidence.mkdir(parents=True)
        files = make_archive(repo, args.sha, evidence)
        (evidence / "intent.json").write_text(json.dumps({
            "release_sha": args.sha, "previous": args.previous,
            "archive_sha256": files["source.tar.gz"][1], "preview_sha256": args.preview_sha256,
        }), encoding="utf-8")
        settings = transport.env()
        if settings["PROXY_VPS_HOST"] != transport.PROXY:
            raise ArchiveError("landing_proxy_identity_mismatch")
        with ssh_client(transport.PROXY, settings["PROXY_VPS_LOGIN"], settings["PROXY_VPS_PASSWORD"]) as client:
            result = execute(client, args.sha, args.previous, args.helper_sha256, files)
        (evidence / "technical-readback.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    except Exception:
        raise SystemExit("BLOCKED: landing release unverified; reconcile archive and current release before retry") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
