from __future__ import annotations

import os
import re
import stat
import zipfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as StdElementTree

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException


class AsyncUpload(Protocol):
    async def read(self, size: int) -> bytes: ...


@dataclass(frozen=True)
class ScormIntakeLimits:
    zip_bytes: int = int(os.getenv("MAX_SCORM_ZIP_BYTES", str(250 * 1024 * 1024)))
    files: int = int(os.getenv("MAX_SCORM_FILES", "5000"))
    uncompressed_bytes: int = int(os.getenv("MAX_SCORM_UNCOMPRESSED_BYTES", str(500 * 1024 * 1024)))
    entry_bytes: int = int(os.getenv("MAX_SCORM_ENTRY_BYTES", str(100 * 1024 * 1024)))
    compression_ratio: int = int(os.getenv("MAX_SCORM_COMPRESSION_RATIO", "100"))
    manifest_bytes: int = int(os.getenv("MAX_SCORM_MANIFEST_BYTES", str(2 * 1024 * 1024)))
    read_chunk_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class ScormManifest:
    manifest_file: str
    title: str
    version: str
    entrypoint: str
    entrypoint_exists: bool
    default_organization: str | None
    resource_id: str | None
    file_count: int

    def as_dict(self) -> dict[str, str | bool | int | None]:
        return asdict(self)


@dataclass(frozen=True)
class ValidatedScormPackage:
    content: bytes
    manifest: ScormManifest


class ScormIntakeError(ValueError):
    def __init__(self, code: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class ScormPackageIntake:
    """Validate an untrusted SCORM archive before any persistent side effect."""

    def __init__(self, limits: ScormIntakeLimits | None = None) -> None:
        self._limits = limits or ScormIntakeLimits()

    async def inspect(self, upload: AsyncUpload, content_length: str | int | None) -> ValidatedScormPackage:
        self._validate_declared_length(content_length)
        content = await self._read_bounded(upload)
        if not content:
            raise ScormIntakeError("zip_empty", 400, "SCORM ZIP is empty")

        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = self._inspect_archive(archive)
                manifest = self._parse_manifest(archive, names)
        except zipfile.BadZipFile:
            raise ScormIntakeError("invalid_zip", 400, "Uploaded file is not a valid ZIP") from None

        if manifest.version != "scorm_1_2":
            raise ScormIntakeError("unsupported_scorm_version", 400, "Only SCORM 1.2 is supported")
        return ValidatedScormPackage(content=content, manifest=manifest)

    def _validate_declared_length(self, content_length: str | int | None) -> None:
        if content_length is None or content_length == "":
            return
        try:
            declared = content_length if isinstance(content_length, int) else int(content_length)
        except (TypeError, ValueError):
            raise ScormIntakeError("invalid_content_length", 400, "Invalid Content-Length") from None
        if declared < 0:
            raise ScormIntakeError("invalid_content_length", 400, "Invalid Content-Length")
        if declared > self._limits.zip_bytes:
            raise ScormIntakeError("zip_too_large", 413, "SCORM ZIP is too large")

    async def _read_bounded(self, upload: AsyncUpload) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while chunk := await upload.read(self._limits.read_chunk_bytes):
            total += len(chunk)
            if total > self._limits.zip_bytes:
                raise ScormIntakeError("zip_too_large", 413, "SCORM ZIP is too large")
            chunks.append(chunk)
        return b"".join(chunks)

    def _inspect_archive(self, archive: zipfile.ZipFile) -> tuple[str, ...]:
        members = archive.infolist()
        if len(members) > self._limits.files:
            raise ScormIntakeError(
                "archive_too_many_files",
                400,
                f"SCORM ZIP contains more than {self._limits.files} entries",
            )
        names: list[str] = []
        seen: set[str] = set()
        total_uncompressed = 0

        for info in members:
            raw_name = info.filename
            normalized = raw_name.replace("\\", "/")
            if not normalized or normalized.endswith("/"):
                continue
            path = PurePosixPath(normalized)
            decoded_path = PurePosixPath(unquote(normalized))
            if (
                "\x00" in normalized
                or normalized != normalized.strip()
                or path.is_absolute()
                or decoded_path.is_absolute()
                or ".." in path.parts
                or ".." in decoded_path.parts
                or _WINDOWS_DRIVE.match(normalized)
            ):
                raise ScormIntakeError("archive_unsafe_path", 400, "SCORM ZIP contains unsafe file paths")
            if info.flag_bits & 0x1:
                raise ScormIntakeError("archive_encrypted", 400, "SCORM ZIP contains encrypted entries")
            unix_mode = info.external_attr >> 16
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise ScormIntakeError("archive_link_forbidden", 400, "SCORM ZIP contains symbolic links")

            identity = normalized.casefold()
            if identity in seen:
                raise ScormIntakeError("archive_duplicate_path", 400, "SCORM ZIP contains duplicate file paths")
            seen.add(identity)

            if info.file_size > self._limits.entry_bytes:
                raise ScormIntakeError(
                    "archive_entry_too_large",
                    400,
                    "SCORM ZIP entry exceeds the allowed uncompressed size",
                )
            total_uncompressed += info.file_size
            if total_uncompressed > self._limits.uncompressed_bytes:
                raise ScormIntakeError(
                    "archive_expansion_too_large",
                    400,
                    "SCORM ZIP exceeds the allowed uncompressed size",
                )
            if info.file_size and info.compress_size == 0:
                raise ScormIntakeError("archive_invalid_entry", 400, "SCORM ZIP contains an invalid compressed entry")
            if info.compress_size and info.file_size / info.compress_size > self._limits.compression_ratio:
                raise ScormIntakeError(
                    "archive_compression_ratio",
                    400,
                    "SCORM ZIP compression ratio is too high",
                )
            names.append(normalized)
        return tuple(names)

    def _parse_manifest(self, archive: zipfile.ZipFile, names: tuple[str, ...]) -> ScormManifest:
        manifest_names = [name for name in names if PurePosixPath(name).name.casefold() == "imsmanifest.xml"]
        if not manifest_names:
            raise ScormIntakeError("manifest_missing", 400, "SCORM package must contain imsmanifest.xml")
        if len(manifest_names) != 1:
            raise ScormIntakeError("manifest_ambiguous", 400, "SCORM package contains multiple manifests")

        manifest_name = manifest_names[0]
        manifest_info = next(
            info for info in archive.infolist() if info.filename.replace("\\", "/") == manifest_name
        )
        if manifest_info.file_size > self._limits.manifest_bytes:
            raise ScormIntakeError("manifest_too_large", 400, "SCORM manifest exceeds the allowed size")
        with archive.open(manifest_info) as manifest_file:
            manifest_bytes = manifest_file.read(self._limits.manifest_bytes + 1)
        if len(manifest_bytes) > self._limits.manifest_bytes:
            raise ScormIntakeError("manifest_too_large", 400, "SCORM manifest exceeds the allowed size")

        try:
            root = DefusedElementTree.fromstring(manifest_bytes, forbid_dtd=True)
        except DefusedXmlException:
            raise ScormIntakeError(
                "manifest_forbidden_xml",
                400,
                "imsmanifest.xml contains forbidden XML constructs",
            ) from None
        except StdElementTree.ParseError:
            raise ScormIntakeError("manifest_invalid_xml", 400, "imsmanifest.xml is not valid XML") from None

        namespace = {
            "imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
            "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
        }
        organizations = root.find("imscp:organizations", namespace)
        default_organization = organizations.attrib.get("default") if organizations is not None else None
        organization = None
        if organizations is not None:
            candidates = organizations.findall("imscp:organization", namespace)
            organization = next(
                (candidate for candidate in candidates if candidate.attrib.get("identifier") == default_organization),
                candidates[0] if candidates else None,
            )

        title = self._text_of(organization, "imscp:title", namespace) if organization is not None else None
        item = organization.find(".//imscp:item", namespace) if organization is not None else None
        resource_id = item.attrib.get("identifierref") if item is not None else None
        resources = root.findall(".//imscp:resource", namespace)
        resource = next(
            (candidate for candidate in resources if resource_id and candidate.attrib.get("identifier") == resource_id),
            None,
        )
        if resource is None:
            resource = next((candidate for candidate in resources if candidate.attrib.get("href")), None)
        if resource is None:
            raise ScormIntakeError("manifest_no_resource", 400, "SCORM manifest has no launchable resource")

        href = (resource.attrib.get("href") or "").strip()
        if not href:
            raise ScormIntakeError("manifest_no_href", 400, "SCORM launch resource has no href")
        parsed_href = urlsplit(href)
        decoded_href_path = self._fully_decode_path(parsed_href.path)
        decoded_url = urlsplit(decoded_href_path)
        href_path = PurePosixPath(decoded_href_path)
        if (
            parsed_href.scheme
            or parsed_href.netloc
            or decoded_url.scheme
            or decoded_url.netloc
            or "\\" in decoded_href_path
            or href_path.is_absolute()
            or ".." in href_path.parts
            or _WINDOWS_DRIVE.match(decoded_href_path)
        ):
            raise ScormIntakeError("manifest_unsafe_href", 400, "SCORM manifest contains unsafe launch path")

        version = self._detect_version(root, namespace)
        manifest_dir = str(PurePosixPath(manifest_name).parent)
        entrypoint_path = parsed_href.path if manifest_dir == "." else f"{manifest_dir}/{parsed_href.path}"
        entrypoint = entrypoint_path
        if parsed_href.query:
            entrypoint += f"?{parsed_href.query}"
        if parsed_href.fragment:
            entrypoint += f"#{parsed_href.fragment}"
        entrypoint_exists = entrypoint_path.casefold() in {name.casefold() for name in names}

        return ScormManifest(
            manifest_file=manifest_name,
            title=title or "SCORM курс",
            version=version,
            entrypoint=entrypoint,
            entrypoint_exists=entrypoint_exists,
            default_organization=default_organization,
            resource_id=resource_id,
            file_count=len(names),
        )

    @staticmethod
    def _fully_decode_path(value: str) -> str:
        decoded = value
        for _ in range(8):
            next_value = unquote(decoded)
            if next_value == decoded:
                return decoded
            decoded = next_value
        raise ScormIntakeError("manifest_unsafe_href", 400, "SCORM manifest contains unsafe launch path")

    @staticmethod
    def _text_of(
        root: StdElementTree.Element,
        xpath: str,
        namespace: dict[str, str],
    ) -> str | None:
        element = root.find(xpath, namespace)
        if element is None or element.text is None:
            return None
        value = element.text.strip()
        return value or None

    @classmethod
    def _detect_version(cls, root: StdElementTree.Element, namespace: dict[str, str]) -> str:
        schema_version = cls._text_of(root, "imscp:metadata/imscp:schemaversion", namespace)
        if schema_version:
            lowered = schema_version.lower()
            if "2004" in lowered:
                return "scorm_2004"
            if "1.2" in lowered or "1,2" in lowered:
                return "scorm_1_2"

        for element in root.iter():
            tag = element.tag if isinstance(element.tag, str) else ""
            if "adlcp_v1p3" in tag or "adlcp2004" in tag:
                return "scorm_2004"
            for attribute in element.attrib:
                if "adlcp_v1p3" in attribute or "adlcp2004" in attribute:
                    return "scorm_2004"
        return "scorm_1_2"
