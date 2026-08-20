"""Pure workbook-analysis helpers for staff import."""

from .analysis import (
    HeaderCandidate,
    HeaderMatch,
    LoadedStaffSheet,
    StaffWorkbookAnalysis,
    StaffWorkbookSheetInspection,
    analyze_staff_workbook,
    compute_workbook_signature,
)
from .loaders import (
    MAX_ANALYSIS_COLUMNS,
    MAX_ANALYSIS_ROWS,
    WorkbookAnalysisLimitError,
    load_staff_workbook,
)

__all__ = [
    "HeaderCandidate",
    "HeaderMatch",
    "LoadedStaffSheet",
    "StaffWorkbookAnalysis",
    "StaffWorkbookSheetInspection",
    "analyze_staff_workbook",
    "compute_workbook_signature",
    "MAX_ANALYSIS_COLUMNS",
    "MAX_ANALYSIS_ROWS",
    "WorkbookAnalysisLimitError",
    "load_staff_workbook",
]
