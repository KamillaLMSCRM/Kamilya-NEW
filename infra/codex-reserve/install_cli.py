"""Install the pinned official Codex CLI binary without trusting archive metadata."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import stat
import tarfile
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


URL = "https://registry.npmjs.org/@openai/codex/-/codex-0.146.1-linux-x64.tgz"
EXPECTED_SHA512_B64 = "XPWpWzJgGK1ygsUBMXgskEkr+uTVj/XOnnCP2UE9tQUXTWYRYElz7QW1YS3bxkN6Kev4CJQKbdJopVwh+0E/TQ=="
MEMBER = "package/vendor/x86_64-unknown-linux-musl/bin/codex"
# Registry metadata for this exact integrity-pinned release: unpacked366619458
# bytes/8 files. The archive is larger than128MiB; retain a finite384MiB ceiling.
MAX_DOWNLOAD_BYTES = 384 * 1024 * 1024
TIMEOUT_SECONDS = 30
TARGET = Path("/usr/local/bin/codex")
SHA_FILE = Path("/opt/codex-reserve/cli.sha256")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, msg, headers, new_url):  # noqa: ANN001
        raise URLError("redirects are not permitted")


def download() -> bytes:
    request = Request(URL, headers={"Accept": "application/octet-stream", "User-Agent": "kamilya-codex-reserve/1"})
    opener = build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            content = bytearray()
            while chunk := response.read(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("Codex CLI archive exceeds the download limit")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Codex CLI download failed: {exc}") from exc
    archive = bytes(content)
    actual = base64.b64encode(hashlib.sha512(archive).digest()).decode("ascii")
    if not hmac.compare_digest(actual, EXPECTED_SHA512_B64):
        raise RuntimeError("Codex CLI archive SHA-512 does not match the pinned digest")
    return archive


def extract_binary(archive: bytes) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            matches = [member for member in tar.getmembers() if member.name == MEMBER]
            if len(matches) != 1 or not matches[0].isreg() or not 0 < matches[0].size <= 366619458:
                raise RuntimeError("Codex CLI archive has no unique regular pinned binary")
            extracted = tar.extractfile(matches[0])
            if extracted is None:
                raise RuntimeError("Codex CLI binary cannot be read")
            binary = extracted.read()
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError(f"Codex CLI archive is invalid: {exc}") from exc
    if not binary:
        raise RuntimeError("Codex CLI binary is empty")
    return binary


def write_binary(binary: bytes) -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    SHA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=TARGET.parent, prefix=".codex-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(binary)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        os.replace(temporary, TARGET)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(binary).hexdigest() + "\n"
    SHA_FILE.write_text(digest, encoding="ascii")
    os.chmod(SHA_FILE, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("install_cli.py must run as root")
    write_binary(extract_binary(download()))


if __name__ == "__main__":
    main()
