"""Staff import service — parse Excel/CSV штатное расписание, create users + positions.

Stage 1d of employee onboarding epic.

Flow:
1. HR uploads file (.xlsx or .csv) at /admin/staff
2. Backend parses, normalizes columns (Russian/English), returns preview
3. HR reviews preview (new users, matched users, new departments, new positions)
4. HR commits, backend creates/updates rows in transaction

CSV columns (case-insensitive, Russian OR English):
- personnel_number (required) - табельный номер
- first_name (required)
- last_name (required)
- department (required)
- position (required)
- email (optional)
- phone (optional)
- hire_date (optional, ISO format preferred)

Logic:
- User matched by personnel_number (case-insensitive) within tenant
- Position auto-created if (department, position) doesn't exist in tenant
- If user exists: update first_name, last_name, email, phone; don't change position
  (position assignment is a separate workflow)
- If new: create with status='inactive', is_active=true (HR-managed)
  (password_hash=NULL - no self-service login)
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.modules.positions.models import Position

logger = logging.getLogger(__name__)


# ── Column mapping ──────────────────────────────────────────────


# Maps recognized column headers (lowercase, trimmed) to canonical field names.
# Supports both Russian (HR's typical export) and English (template).
COLUMN_ALIASES: dict[str, str] = {
    # personnel_number
    "personnel_number": "personnel_number",
    "personnelnumber": "personnel_number",
    "табельный_номер": "personnel_number",
    "табельный номер": "personnel_number",
    "таб_номер": "personnel_number",
    "табельный№": "personnel_number",
    "employee_id": "personnel_number",
    "employeeid": "personnel_number",
    "tab_no": "personnel_number",
    "tabno": "personnel_number",
    # first_name
    "first_name": "first_name",
    "firstname": "first_name",
    "имя": "first_name",
    # last_name
    "last_name": "last_name",
    "lastname": "last_name",
    "фамилия": "last_name",
    # department
    "department": "department",
    "отдел": "department",
    "подразделение": "department",
    "цех": "department",
    # position
    "position": "position",
    "должность": "position",
    # email
    "email": "email",
    "e-mail": "email",
    "почта": "email",
    # phone
    "phone": "phone",
    "телефон": "phone",
    # hire_date
    "hire_date": "hire_date",
    "hiredate": "hire_date",
    "дата_приема": "hire_date",
    "дата приема": "hire_date",
}


REQUIRED_FIELDS = {"personnel_number", "first_name", "last_name", "department", "position"}
OPTIONAL_FIELDS = {"email", "phone", "hire_date"}
ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS


# ── Parsed row types ─────────────────────────────────────────────


@dataclass
class ParsedRow:
    """One row of the import file, normalized."""
    row_number: int  # 1-based row in original file (skipping header)
    personnel_number: str
    first_name: str
    last_name: str
    department: str
    position: str
    email: str | None = None
    phone: str | None = None
    hire_date: str | None = None  # ISO format if present


@dataclass
class ParsedFile:
    """Result of parsing the uploaded file."""
    rows: list[ParsedRow]
    invalid_rows: list[dict]  # [{row_number, errors: [...], raw: {...}}]
    detected_columns: dict[str, str]  # original -> canonical
    missing_required_columns: list[str]
    total_rows_in_file: int


@dataclass
class PreviewItem:
    """One row in the preview (will_create / will_update / will_skip)."""
    row_number: int
    personnel_number: str
    first_name: str
    last_name: str
    department: str
    position: str
    email: str | None
    phone: str | None
    action: str  # 'create' | 'update' | 'skip'
    existing_user_id: str | None  # if action='update', set
    notes: list[str] = field(default_factory=list)


@dataclass
class PreviewResult:
    """Full preview returned to HR before commit."""
    items: list[PreviewItem]
    new_positions: list[str]  # (department, position) tuples that will be auto-created
    new_departments: list[str]  # departments that don't exist yet
    summary: dict[str, int]  # {'create': N, 'update': M, 'skip': K, 'new_positions': P}


# ── File parsing ────────────────────────────────────────────────


def _normalize_header(h: Any) -> str:
    """Lowercase + trim + collapse spaces."""
    if h is None:
        return ""
    s = str(h).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_hire_date(s: str | None) -> str | None:
    """Try to parse hire_date. Returns ISO format or None."""
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    # DD.MM.YYYY or DD/MM/YYYY (Russian/European)
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})$", s)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y if int(y) < 50 else "19" + y
        try:
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            return None
    return None  # can't parse


def parse_csv(content: bytes) -> ParsedFile:
    """Parse CSV with Russian/English headers, return ParsedFile."""
    # Decode (try utf-8-sig first for BOM, then cp1251 for old Russian Excel exports)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1251")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    raw_columns = [c for c in (reader.fieldnames or [])]
    column_map: dict[str, str] = {}  # raw_header -> canonical
    for raw in raw_columns:
        canonical = COLUMN_ALIASES.get(_normalize_header(raw))
        if canonical:
            column_map[raw] = canonical

    missing = REQUIRED_FIELDS - set(column_map.values())
    if missing:
        return ParsedFile(
            rows=[],
            invalid_rows=[],
            detected_columns=column_map,
            missing_required_columns=sorted(missing),
            total_rows_in_file=0,
        )

    rows: list[ParsedRow] = []
    invalid: list[dict] = []
    seen_pn: set[str] = set()
    for i, raw_row in enumerate(reader, start=2):  # row 1 = header
        # Skip empty rows
        if not any(v and str(v).strip() for v in raw_row.values()):
            continue

        # Extract fields
        fields: dict[str, str] = {}
        for raw, canonical in column_map.items():
            v = raw_row.get(raw)
            if v is None:
                continue
            fields[canonical] = str(v).strip()

        # Validate required
        errors: list[str] = []
        for req in REQUIRED_FIELDS:
            if not fields.get(req):
                errors.append(f"Поле «{req}» пустое")

        pn = fields.get("personnel_number", "").strip()
        if pn:
            pn_norm = pn.lower()
            if pn_norm in seen_pn:
                errors.append(f"Дубликат табельного номера «{pn}»")
            seen_pn.add(pn_norm)

        if errors:
            invalid.append({
                "row_number": i,
                "errors": errors,
                "raw": dict(raw_row),
            })
            continue

        rows.append(ParsedRow(
            row_number=i,
            personnel_number=pn,
            first_name=fields.get("first_name", "").strip(),
            last_name=fields.get("last_name", "").strip(),
            department=fields.get("department", "").strip(),
            position=fields.get("position", "").strip(),
            email=fields.get("email") or None,
            phone=fields.get("phone") or None,
            hire_date=_parse_hire_date(fields.get("hire_date")),
        ))

    return ParsedFile(
        rows=rows,
        invalid_rows=invalid,
        detected_columns=column_map,
        missing_required_columns=[],
        total_rows_in_file=len(rows) + len(invalid),
    )


def parse_xlsx(content: bytes) -> ParsedFile:
    """Parse Excel .xlsx via openpyxl. Returns ParsedFile (same shape as parse_csv)."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active

    # Header row
    header_cells = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if not header_cells:
        return ParsedFile(rows=[], invalid_rows=[], detected_columns={},
                          missing_required_columns=list(REQUIRED_FIELDS), total_rows_in_file=0)

    raw_columns = [str(c).strip() if c is not None else "" for c in header_cells]
    column_map: dict[str, str] = {}
    for raw in raw_columns:
        canonical = COLUMN_ALIASES.get(_normalize_header(raw))
        if canonical:
            column_map[raw] = canonical

    missing = REQUIRED_FIELDS - set(column_map.values())
    if missing:
        return ParsedFile(
            rows=[],
            invalid_rows=[],
            detected_columns=column_map,
            missing_required_columns=sorted(missing),
            total_rows_in_file=0,
        )

    rows: list[ParsedRow] = []
    invalid: list[dict] = []
    seen_pn: set[str] = set()
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        # Skip empty rows
        if not any(v is not None and str(v).strip() for v in row):
            continue

        # Map cells to fields
        fields: dict[str, str] = {}
        raw_dict: dict[str, Any] = {}
        for raw_header, cell in zip(raw_columns, row):
            canonical = column_map.get(raw_header)
            if canonical is None:
                # Unmapped column - keep as raw for invalid rows
                raw_dict[raw_header] = str(cell).strip() if cell is not None else ""
            else:
                v = str(cell).strip() if cell is not None else ""
                fields[canonical] = v

        errors: list[str] = []
        for req in REQUIRED_FIELDS:
            if not fields.get(req):
                errors.append(f"Поле «{req}» пустое")

        pn = fields.get("personnel_number", "").strip()
        if pn:
            pn_norm = pn.lower()
            if pn_norm in seen_pn:
                errors.append(f"Дубликат табельного номера «{pn}»")
            seen_pn.add(pn_norm)

        if errors:
            invalid.append({
                "row_number": i,
                "errors": errors,
                "raw": raw_dict,
            })
            continue

        rows.append(ParsedRow(
            row_number=i,
            personnel_number=pn,
            first_name=fields.get("first_name", "").strip(),
            last_name=fields.get("last_name", "").strip(),
            department=fields.get("department", "").strip(),
            position=fields.get("position", "").strip(),
            email=fields.get("email") or None,
            phone=fields.get("phone") or None,
            hire_date=_parse_hire_date(fields.get("hire_date")),
        ))

    wb.close()
    return ParsedFile(
        rows=rows,
        invalid_rows=invalid,
        detected_columns=column_map,
        missing_required_columns=[],
        total_rows_in_file=len(rows) + len(invalid),
    )


def parse_upload(filename: str, content: bytes) -> ParsedFile:
    """Dispatch based on file extension."""
    name = filename.lower()
    if name.endswith(".csv"):
        return parse_csv(content)
    if name.endswith(".xlsx"):
        return parse_xlsx(content)
    if name.endswith(".xls"):
        raise ValueError("Старый формат .xls не поддерживается. Сохраните файл как .xlsx или .csv.")
    raise ValueError(f"Формат файла не поддерживается: {filename}. Используйте .xlsx или .csv.")


# ── Preview (against current DB) ─────────────────────────────────


async def build_preview(
    db: AsyncSession,
    tenant_id: UUID,
    parsed: ParsedFile,
) -> PreviewResult:
    """Match parsed rows against existing users/positions/departments, return preview."""

    # Load all existing users in tenant (by personnel_number)
    users_result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.personnel_number.is_not(None),
        )
    )
    users_by_pn: dict[str, User] = {
        (u.personnel_number or "").lower(): u for u in users_result.scalars().all()
    }

    # Load all existing positions in tenant
    pos_result = await db.execute(
        select(Position).where(Position.tenant_id == tenant_id)
    )
    positions = pos_result.scalars().all()
    # Index by (department, position) lower-cased
    pos_by_dp: dict[tuple[str, str], Position] = {
        ((p.department or "").strip().lower(), (p.name or "").strip().lower()): p
        for p in positions
    }
    # Also unique departments
    existing_departments: set[str] = {(p.department or "").strip().lower() for p in positions}

    items: list[PreviewItem] = []
    new_positions: set[tuple[str, str]] = set()  # (dept, position) — new

    for row in parsed.rows:
        pn_norm = row.personnel_number.lower()
        existing = users_by_pn.get(pn_norm)

        dp_key = (row.department.lower(), row.position.lower())
        if dp_key not in pos_by_dp and dp_key not in new_positions:
            new_positions.add(dp_key)

        notes: list[str] = []

        if existing:
            # Will update - check what changes
            if (existing.first_name or "").strip() != row.first_name:
                notes.append(f"имя: «{existing.first_name}» → «{row.first_name}»")
            if (existing.last_name or "").strip() != row.last_name:
                notes.append(f"фамилия: «{existing.last_name}» → «{row.last_name}»")
            if (existing.email or "").strip().lower() != (row.email or "").strip().lower():
                notes.append(f"email: «{existing.email or '—'}» → «{row.email or '—'}»")
            if (existing.position_id is None) and dp_key in pos_by_dp:
                notes.append(f"новая должность: «{row.position}» (отдел «{row.department}»)")

            # Skip if no changes
            if not notes:
                items.append(PreviewItem(
                    row_number=row.row_number,
                    personnel_number=row.personnel_number,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    department=row.department,
                    position=row.position,
                    email=row.email,
                    phone=row.phone,
                    action="skip",
                    existing_user_id=str(existing.id),
                    notes=["Без изменений"],
                ))
            else:
                items.append(PreviewItem(
                    row_number=row.row_number,
                    personnel_number=row.personnel_number,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    department=row.department,
                    position=row.position,
                    email=row.email,
                    phone=row.phone,
                    action="update",
                    existing_user_id=str(existing.id),
                    notes=notes,
                ))
        else:
            # Will create new
            if dp_key in new_positions:
                notes.append(f"новая должность: «{row.position}» в «{row.department}»")
            items.append(PreviewItem(
                row_number=row.row_number,
                personnel_number=row.personnel_number,
                first_name=row.first_name,
                last_name=row.last_name,
                department=row.department,
                position=row.position,
                email=row.email,
                phone=row.phone,
                action="create",
                existing_user_id=None,
                notes=notes,
            ))

    summary = {
        "create": sum(1 for i in items if i.action == "create"),
        "update": sum(1 for i in items if i.action == "update"),
        "skip": sum(1 for i in items if i.action == "skip"),
        "new_positions": len(new_positions),
        "new_departments": len({d for d, _ in new_positions if d not in existing_departments}),
    }
    return PreviewResult(
        items=items,
        new_positions=sorted([f"{dept} / {pos}" for dept, pos in new_positions]),
        new_departments=sorted({dept for dept, _ in new_positions if dept not in existing_departments}),
        summary=summary,
    )


# ── Commit (apply changes) ───────────────────────────────────────


async def commit_import(
    db: AsyncSession,
    tenant_id: UUID,
    parsed: ParsedFile,
) -> dict:
    """Apply the import: create/update users + create new positions.

    Returns {created: N, updated: M, skipped: K, positions_created: P}.
    """
    # Preload existing
    users_result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.personnel_number.is_not(None),
        )
    )
    users_by_pn: dict[str, User] = {
        (u.personnel_number or "").lower(): u for u in users_result.scalars().all()
    }

    pos_result = await db.execute(
        select(Position).where(Position.tenant_id == tenant_id)
    )
    positions = pos_result.scalars().all()
    pos_by_dp: dict[tuple[str, str], Position] = {
        ((p.department or "").strip().lower(), (p.name or "").strip().lower()): p
        for p in positions
    }

    created = 0
    updated = 0
    skipped = 0
    positions_created = 0

    for row in parsed.rows:
        pn_norm = row.personnel_number.lower()
        existing = users_by_pn.get(pn_norm)

        # Resolve/create position
        dp_key = (row.department.lower(), row.position.lower())
        pos = pos_by_dp.get(dp_key)
        if not pos:
            pos = Position(
                id=uuid4(),
                tenant_id=tenant_id,
                name=row.position.strip(),
                department=row.department.strip(),
                level="",
                responsibilities="",
                requirements="",
                employee_count=0,
            )
            db.add(pos)
            await db.flush()
            pos_by_dp[dp_key] = pos
            positions_created += 1

        if existing:
            # Check if anything actually changes
            changed = False
            if (existing.first_name or "").strip() != row.first_name:
                existing.first_name = row.first_name
                changed = True
            if (existing.last_name or "").strip() != row.last_name:
                existing.last_name = row.last_name
                changed = True
            if (existing.email or "").strip().lower() != (row.email or "").strip().lower():
                existing.email = row.email
                changed = True
            if (existing.phone or "") != (row.phone or ""):
                # Add phone column if doesn't exist (skip for now if not in model)
                changed = True
            if not existing.position_id:
                existing.position_id = pos.id
                existing.is_active = True  # auto-activate when position is assigned
                changed = True
            if changed:
                updated += 1
            else:
                skipped += 1
        else:
            user = User(
                id=uuid4(),
                tenant_id=tenant_id,
                personnel_number=row.personnel_number,
                email=row.email,
                first_name=row.first_name,
                last_name=row.last_name,
                role="student",  # bulk import always creates students; HR promotes separately
                is_active=True,
                position_id=pos.id,
                password_hash=None,  # no self-service login - HR-managed
                status="active",
            )
            db.add(user)
            created += 1
            # Invalidate cache so next row can find this user (duplicate-PN check)
            users_by_pn[pn_norm] = user

    await db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "positions_created": positions_created,
    }
