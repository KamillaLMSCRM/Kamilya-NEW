"""Bounded OOXML ZIP preflight before storage or document conversion."""

from __future__ import annotations

import stat
import struct
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO


class ArchivePreflightError(ValueError):
    """Raised when an OOXML archive violates structural or expansion budgets."""


@dataclass(frozen=True)
class ArchiveBudget:
    max_entries: int = 5000
    max_entry_uncompressed_bytes: int = 64 * 1024 * 1024
    max_total_uncompressed_bytes: int = 256 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_name_length: int = 512


@dataclass(frozen=True)
class ArchiveSummary:
    entry_count: int
    total_uncompressed_bytes: int


_REQUIRED_PARTS = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
}
_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_SIZE = 22
_MAX_EOCD_SEARCH = _EOCD_SIZE + 65_535


def _declared_entry_count(source: BinaryIO) -> int:
    """Read the bounded EOCD record before ZipFile materializes filelist."""
    source.seek(0, 2)
    size = source.tell()
    source.seek(max(0, size - _MAX_EOCD_SEARCH))
    tail = source.read(_MAX_EOCD_SEARCH)
    offset = tail.rfind(_EOCD_SIGNATURE)
    if offset < 0 or len(tail) - offset < _EOCD_SIZE:
        raise ArchivePreflightError("invalid OOXML archive directory")
    _, disk_number, directory_disk, disk_entries, total_entries, _, _, comment_length = struct.unpack_from(
        "<4s4H2LH", tail, offset
    )
    if offset + _EOCD_SIZE + comment_length != len(tail):
        raise ArchivePreflightError("invalid OOXML archive directory")
    if disk_number or directory_disk or disk_entries != total_entries:
        raise ArchivePreflightError("multi-disk OOXML archives are not supported")
    if total_entries == 0xFFFF:
        raise ArchivePreflightError("ZIP64 OOXML archives are not supported")
    return total_entries


def _safe_member_name(name: str, *, max_length: int) -> bool:
    if not name or len(name) > max_length or "\x00" in name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def preflight_ooxml(
    source: BinaryIO,
    suffix: str,
    *,
    budget: ArchiveBudget | None = None,
) -> ArchiveSummary:
    """Inspect the ZIP central directory without extracting archive contents."""

    normalized_suffix = suffix.lower()
    required_part = _REQUIRED_PARTS.get(normalized_suffix)
    if required_part is None:
        raise ArchivePreflightError("unsupported OOXML suffix")
    limits = budget or ArchiveBudget()
    original_position = source.tell()
    try:
        source.seek(0)
        declared_entries = _declared_entry_count(source)
        if declared_entries > limits.max_entries:
            raise ArchivePreflightError("OOXML archive has too many entries")
        source.seek(0)
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise ArchivePreflightError("invalid OOXML archive") from exc

        if len(entries) > limits.max_entries:
            raise ArchivePreflightError("OOXML archive has too many entries")
        if len(entries) != declared_entries:
            raise ArchivePreflightError("OOXML archive directory count is inconsistent")

        names: set[str] = set()
        total_uncompressed = 0
        total_compressed = 0
        for entry in entries:
            if not _safe_member_name(entry.filename, max_length=limits.max_name_length):
                raise ArchivePreflightError("OOXML archive contains an unsafe path")
            if entry.flag_bits & 0x1:
                raise ArchivePreflightError("encrypted OOXML entries are not supported")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArchivePreflightError("OOXML archive contains a symbolic link")
            if entry.file_size > limits.max_entry_uncompressed_bytes:
                raise ArchivePreflightError("OOXML entry exceeds the uncompressed size limit")
            if entry.file_size and entry.file_size / max(entry.compress_size, 1) > limits.max_compression_ratio:
                raise ArchivePreflightError("OOXML entry exceeds the compression ratio limit")
            names.add(entry.filename.rstrip("/"))
            total_uncompressed += entry.file_size
            total_compressed += entry.compress_size
            if total_uncompressed > limits.max_total_uncompressed_bytes:
                raise ArchivePreflightError("OOXML archive exceeds the total uncompressed size limit")

        if total_uncompressed and total_uncompressed / max(total_compressed, 1) > limits.max_compression_ratio:
            raise ArchivePreflightError("OOXML archive exceeds the compression ratio limit")
        if "[Content_Types].xml" not in names or required_part not in names:
            raise ArchivePreflightError("OOXML archive is missing a required OOXML part")
        return ArchiveSummary(entry_count=len(entries), total_uncompressed_bytes=total_uncompressed)
    finally:
        source.seek(original_position)
