"""Compatibility adapter for the historical flat staff workbook format."""

from .adapter import (
    LEGACY_ROOT_EXTERNAL_KEY,
    LegacyColumnMap,
    LegacyStaffRow,
    adapt_legacy_rows,
)

__all__ = [
    "LEGACY_ROOT_EXTERNAL_KEY",
    "LegacyColumnMap",
    "LegacyStaffRow",
    "adapt_legacy_rows",
]
