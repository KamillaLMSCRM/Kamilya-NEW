from __future__ import annotations

import io
import stat
import zipfile

import pytest

from app.modules.scorm.package_intake import (
    ScormIntakeError,
    ScormIntakeLimits,
    ScormPackageIntake,
)


class MemoryUpload:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _manifest(*, version: str = "1.2", href: str = "index.html", extra: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  {extra}
  <metadata><schema>ADL SCORM</schema><schemaversion>{version}</schemaversion></metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>Safe course</title>
      <item identifier="ITEM-1" identifierref="RES-1" />
    </organization>
  </organizations>
  <resources><resource identifier="RES-1" adlcp:scormtype="sco" href="{href}" /></resources>
</manifest>"""


def _zip_bytes(
    manifest: str,
    *,
    extra_files: list[tuple[str | zipfile.ZipInfo, bytes]] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("imsmanifest.xml", manifest)
        archive.writestr("index.html", b"<html></html>")
        for name, content in extra_files or []:
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_inspect_accepts_bounded_scorm_12_package() -> None:
    result = await ScormPackageIntake().inspect(MemoryUpload(_zip_bytes(_manifest())), None)

    assert result.manifest.version == "scorm_1_2"
    assert result.manifest.title == "Safe course"
    assert result.manifest.entrypoint == "index.html"
    assert result.manifest.entrypoint_exists is True
    assert result.manifest.file_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "xml",
    [
        """<?xml version="1.0"?>
<!DOCTYPE manifest [<!ENTITY x "expanded">]>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">&x;</manifest>""",
        """<?xml version="1.0"?>
<!DOCTYPE manifest>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" />""",
        """<?xml version="1.0"?>
<!DOCTYPE manifest [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">&x;</manifest>""",
        """<?xml version="1.0"?>
<!DOCTYPE manifest [
  <!ENTITY a "ha">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">
  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">
]>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">&c;</manifest>""",
        """<?xml version="1.0"?>
<!DOCTYPE manifest [<!ENTITY block "0123456789">]>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  &block;&block;&block;&block;&block;&block;&block;&block;
</manifest>""",
    ],
    ids=["internal-entity", "dtd", "external-entity", "exponential-expansion", "quadratic-expansion"],
)
async def test_inspect_rejects_dtd_and_entities(xml: str) -> None:
    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(MemoryUpload(_zip_bytes(xml)), None)

    assert caught.value.code == "manifest_forbidden_xml"
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_inspect_rejects_unsafe_archive_path() -> None:
    data = _zip_bytes(_manifest(), extra_files=[("../escape.js", b"bad")])

    with pytest.raises(ScormIntakeError, match="unsafe file paths"):
        await ScormPackageIntake().inspect(MemoryUpload(data), None)


@pytest.mark.asyncio
async def test_inspect_rejects_symlink_entry() -> None:
    link = zipfile.ZipInfo("linked.js")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    data = _zip_bytes(_manifest(), extra_files=[(link, b"index.html")])

    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(MemoryUpload(data), None)

    assert caught.value.code == "archive_link_forbidden"


@pytest.mark.asyncio
async def test_inspect_rejects_duplicate_normalized_path() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        data = _zip_bytes(
            _manifest(),
            extra_files=[("content\\lesson.js", b"one"), ("content/lesson.js", b"two")],
        )

    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(MemoryUpload(data), None)

    assert caught.value.code == "archive_duplicate_path"


@pytest.mark.asyncio
async def test_inspect_rejects_ambiguous_manifest() -> None:
    data = _zip_bytes(_manifest(), extra_files=[("nested/imsmanifest.xml", _manifest().encode())])

    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(MemoryUpload(data), None)

    assert caught.value.code == "manifest_ambiguous"


@pytest.mark.asyncio
async def test_inspect_counts_directory_entries_toward_archive_budget() -> None:
    data = _zip_bytes(_manifest(), extra_files=[("empty/", b"")])
    intake = ScormPackageIntake(ScormIntakeLimits(files=2))

    with pytest.raises(ScormIntakeError) as caught:
        await intake.inspect(MemoryUpload(data), None)

    assert caught.value.code == "archive_too_many_files"


@pytest.mark.asyncio
async def test_inspect_rejects_unsupported_scorm_2004() -> None:
    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(MemoryUpload(_zip_bytes(_manifest(version="2004 4th Edition"))), None)

    assert caught.value.code == "unsupported_scorm_version"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "href",
    ["/absolute/index.html", "https://evil.example/index.html", "%2e%2e/index.html", "%252e%252e/index.html"],
)
async def test_inspect_rejects_unsafe_launch_href(href: str) -> None:
    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(MemoryUpload(_zip_bytes(_manifest(href=href))), None)

    assert caught.value.code == "manifest_unsafe_href"


@pytest.mark.asyncio
async def test_inspect_enforces_stream_and_manifest_budgets() -> None:
    data = _zip_bytes(_manifest())
    intake = ScormPackageIntake(ScormIntakeLimits(zip_bytes=len(data) - 1))

    with pytest.raises(ScormIntakeError) as caught:
        await intake.inspect(MemoryUpload(data), None)

    assert caught.value.code == "zip_too_large"
    assert caught.value.status_code == 413

    manifest_limited = ScormPackageIntake(ScormIntakeLimits(manifest_bytes=16))
    with pytest.raises(ScormIntakeError) as caught:
        await manifest_limited.inspect(MemoryUpload(data), None)
    assert caught.value.code == "manifest_too_large"


@pytest.mark.asyncio
async def test_inspect_rejects_invalid_content_length_without_reading_upload() -> None:
    upload = MemoryUpload(_zip_bytes(_manifest()))

    with pytest.raises(ScormIntakeError) as caught:
        await ScormPackageIntake().inspect(upload, "not-a-number")

    assert caught.value.code == "invalid_content_length"
    assert upload._offset == 0
