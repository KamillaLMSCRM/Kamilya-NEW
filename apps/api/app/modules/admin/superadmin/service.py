"""Business logic for superadmin tenant + admin management."""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import argon2
from sqlalchemy import desc, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tenants import Tenant, TenantLead, TenantUsage
from app.models.user_roles import UserRole
from app.models.users import User, UserInvitation
from app.modules.admin.superadmin.schemas import (
    AdminCreate,
    AdminResponse,
    AdminUpdate,
    TenantCreate,
    TenantLeadInfo,
    TenantResponse,
    TenantStats,
    TenantUpdate,
    TenantUsageInfo,
)
from app.modules.users.invitations_service import _build_invite_url

logger = logging.getLogger(__name__)
_ph = argon2.PasswordHasher()


# Roles a superadmin can grant via the admin-management UI. We do NOT
# allow creating *other* superadmins from here — that's a deliberate
# privilege-escalation guard. Use direct DB access for that.
GRANTABLE_ROLES = {"admin", "org_admin", "teacher"}


class SuperadminService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Tenants ────────────────────────────────────────────────────

    async def list_tenants(
        self, search: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[Tenant], int]:
        """List tenants with optional name/slug search.

        Returns (tenants, total_count). total is computed via a separate
        COUNT(*) so the list query stays simple.
        """
        base_query = select(Tenant)
        if search:
            like = f"%{search.lower()}%"
            base_query = base_query.where(
                func.lower(Tenant.name).like(like)
                | func.lower(Tenant.slug).like(like)
            )

        # Total count
        count_q = select(func.count()).select_from(base_query.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0

        # Page
        page_q = base_query.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(page_q)
        return list(result.scalars().all()), int(total)

    async def get_tenant(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self.db.get(Tenant, tenant_id)

    async def get_tenant_stats(self, tenant_id: uuid.UUID) -> TenantStats:
        """Aggregate per-tenant usage counters."""
        # Users
        user_count_q = select(func.count(User.id)).where(User.tenant_id == tenant_id)
        active_user_q = user_count_q.where(User.is_active.is_(True))
        admin_role_q = user_count_q.where(User.role.in_(["admin", "org_admin", "teacher"]))
        user_count = (await self.db.execute(user_count_q)).scalar() or 0
        active_user_count = (await self.db.execute(active_user_q)).scalar() or 0
        admin_count = (await self.db.execute(admin_role_q)).scalar() or 0

        # Courses, documents, enrollments, last activity
        from app.models.courses import Course
        from app.models.document import Document
        from app.models.enrollment import Enrollment

        course_count_q = select(func.count(Course.id)).where(Course.tenant_id == tenant_id)
        published_count_q = course_count_q.where(Course.status == "published")
        doc_count_q = select(func.count(Document.id)).where(Document.tenant_id == tenant_id)
        enr_count_q = select(func.count(Enrollment.id)).where(Enrollment.tenant_id == tenant_id)
        last_login_q = select(func.max(User.last_login)).where(User.tenant_id == tenant_id)

        course_count = (await self.db.execute(course_count_q)).scalar() or 0
        published_count = (await self.db.execute(published_count_q)).scalar() or 0
        doc_count = (await self.db.execute(doc_count_q)).scalar() or 0
        enr_count = (await self.db.execute(enr_count_q)).scalar() or 0
        last_activity = (await self.db.execute(last_login_q)).scalar()

        return TenantStats(
            user_count=int(user_count),
            active_user_count=int(active_user_count),
            admin_count=int(admin_count),
            course_count=int(course_count),
            published_course_count=int(published_count),
            document_count=int(doc_count),
            enrollment_count=int(enr_count),
            last_activity_at=last_activity,
        )

    async def get_tenant_usage(self, tenant_id: uuid.UUID) -> TenantUsageInfo | None:
        usage = await self.db.get(TenantUsage, tenant_id)
        if usage is None:
            return None
        return TenantUsageInfo(
            ai_course_generations_used=int(usage.ai_course_generations_used or 0),
            jd_course_generations_used=int(usage.jd_course_generations_used or 0),
            active_students_count_snapshot=int(usage.active_students_count_snapshot or 0),
            system_users_count_snapshot=int(usage.system_users_count_snapshot or 0),
            updated_at=usage.updated_at,
        )

    async def get_latest_lead(self, tenant_id: uuid.UUID) -> TenantLeadInfo | None:
        result = await self.db.execute(
            select(TenantLead)
            .where(TenantLead.tenant_id == tenant_id)
            .order_by(desc(TenantLead.created_at))
            .limit(1)
        )
        lead = result.scalar_one_or_none()
        if lead is None:
            return None
        return TenantLeadInfo.model_validate(lead)

    async def create_tenant(self, payload: TenantCreate) -> Tenant:
        # Slug uniqueness is enforced by DB unique index; catch and re-raise.
        now = datetime.now(timezone.utc).replace(microsecond=0)
        settings = {
            **(payload.notes and {"superadmin_notes": payload.notes} or {}),
            "trial_limits": {
                "ai_course_generations_limit": 1,
                "jd_course_generations_limit": 1,
                "max_students": payload.max_users or 10,
                "system_users_limit": 3,
                "trial_days": 14,
            },
            "telegram_bot_mode": "shared",
        }
        tenant = Tenant(
            name=payload.name,
            slug=payload.slug,
            plan=payload.plan,
            status=payload.status,
            trial_started_at=now if payload.status == "trial" or payload.plan == "trial" else None,
            trial_ends_at=payload.trial_ends_at,
            paid_until=payload.paid_until,
            max_users=payload.max_users,
            max_courses_per_month=payload.max_courses_per_month,
            notes=payload.notes,
            billing_contact_email=payload.first_admin.email if payload.first_admin else None,
            billing_company_name=payload.name,
            settings=settings,
        )
        self.db.add(tenant)
        try:
            await self.db.flush()
        except IntegrityError as e:
            raise ValueError(f"Slug '{payload.slug}' is already taken") from e
        logger.info("superadmin.tenant.created id=%s slug=%s", tenant.id, tenant.slug)
        return tenant

    async def create_tenant_wizard(
        self, payload: TenantCreate, superadmin_id: uuid.UUID
    ) -> tuple[Tenant, User | None, UserInvitation | None, str | None]:
        """Create tenant plus optional first admin in one transaction."""
        tenant = await self.create_tenant(payload)
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant.id)},
        )

        usage = TenantUsage(
            tenant_id=tenant.id,
            active_students_count_snapshot=0,
            system_users_count_snapshot=1 if payload.first_admin else 0,
        )
        self.db.add(usage)

        admin: User | None = None
        invite: UserInvitation | None = None
        invite_url: str | None = None
        if payload.first_admin:
            admin, invite = await self.create_admin(
                tenant.id, payload.first_admin, superadmin_id=superadmin_id, commit=False
            )
            if invite:
                settings = get_settings()
                invite_url = _build_invite_url(invite.token, getattr(settings, "PUBLIC_URL", None))

        return tenant, admin, invite, invite_url

    async def update_tenant(
        self, tenant_id: uuid.UUID, payload: TenantUpdate
    ) -> Tenant:
        tenant = await self.db.get(Tenant, tenant_id)
        if tenant is None:
            raise LookupError(f"Tenant {tenant_id} not found")

        changes: dict = {}
        for field in (
            "name", "slug", "status", "plan", "trial_ends_at", "paid_until",
            "max_users", "max_courses_per_month", "notes", "settings",
        ):
            new_value = getattr(payload, field)
            if new_value is not None and getattr(tenant, field) != new_value:
                changes[field] = {"from": getattr(tenant, field), "to": new_value}
                setattr(tenant, field, new_value)

        if not changes:
            return tenant
        try:
            await self.db.flush()
        except IntegrityError as e:
            raise ValueError(f"Slug '{payload.slug}' is already taken") from e
        logger.info(
            "superadmin.tenant.updated id=%s changes=%s", tenant.id, list(changes.keys())
        )
        return tenant

    # ── Admins (per-tenant users) ──────────────────────────────────

    async def list_admins(self, tenant_id: uuid.UUID) -> list[User]:
        """List users in a tenant that have elevated roles."""
        result = await self.db.execute(
            select(User)
            .where(
                User.tenant_id == tenant_id,
                User.role.in_(["admin", "org_admin", "teacher"]),
            )
            .order_by(User.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_admin(
        self,
        tenant_id: uuid.UUID,
        payload: AdminCreate,
        superadmin_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> tuple[User, UserInvitation | None]:
        """Add a user with an admin role to a tenant.

        Returns (user, invite_or_none). If `send_invite` is True and
        `email` is set, a UserInvitation row is also created so the new
        admin can set their password via the standard invite flow.
        """
        if payload.role not in GRANTABLE_ROLES:
            raise ValueError(
                f"Cannot grant role '{payload.role}' from superadmin UI"
            )

        # Idempotent: if a user with this email or telegram_id already
        # exists in this tenant, promote them rather than error.
        existing = await self._find_existing_user(tenant_id, payload)
        if existing is not None:
            existing.role = payload.role
            existing.is_active = payload.is_active
            existing.first_name = payload.first_name
            existing.last_name = payload.last_name
            # Update telegram_id if it was provided and missing.
            if payload.telegram_id and not existing.telegram_id:
                existing.telegram_id = payload.telegram_id
            await self._sync_user_role(existing.id, tenant_id, payload.role)
            if commit:
                await self.db.commit()
                await self.db.refresh(existing)
            else:
                await self.db.flush()
            logger.info(
                "superadmin.admin.promoted id=%s tenant=%s role=%s",
                existing.id, tenant_id, payload.role,
            )
            return existing, None

        # Build a temp password — only used if email is set; otherwise
        # the user logs in via Telegram and the hash is just a placeholder.
        temp_pw = secrets.token_urlsafe(16) if payload.email else "telegram-only"

        user = User(
            tenant_id=tenant_id,
            email=payload.email,
            telegram_id=payload.telegram_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
            is_active=payload.is_active,
            status="active",
            password_hash=_ph.hash(temp_pw),
        )
        self.db.add(user)
        await self.db.flush()
        await self._sync_user_role(user.id, tenant_id, payload.role)

        invite: UserInvitation | None = None
        if payload.send_invite and payload.email:
            # Use tenant's invite expiry default (3 days).
            invite = UserInvitation(
                tenant_id=tenant_id,
                email=payload.email,
                first_name=payload.first_name,
                last_name=payload.last_name,
                role=payload.role,
                invited_by=superadmin_id,
                token=secrets.token_urlsafe(32),
                status="pending",
                expires_at=datetime.now(timezone.utc).replace(microsecond=0)
                + timedelta(days=3),
            )
            self.db.add(invite)

        if commit:
            await self.db.commit()
            await self.db.refresh(user)
            if invite:
                await self.db.refresh(invite)
        else:
            await self.db.flush()
        logger.info(
            "superadmin.admin.created id=%s tenant=%s role=%s by=%s",
            user.id, tenant_id, payload.role, superadmin_id,
        )
        return user, invite

    async def _sync_user_role(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str
    ) -> None:
        existing_role = (
            await self.db.execute(
                select(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if existing_role:
            existing_role.role = role
        else:
            self.db.add(UserRole(user_id=user_id, tenant_id=tenant_id, role=role))
        await self.db.flush()

    async def update_admin(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: AdminUpdate
    ) -> User:
        user = await self._get_user_in_tenant(tenant_id, user_id)
        changes: dict = {}
        for field in ("role", "is_active", "first_name", "last_name"):
            new_value = getattr(payload, field)
            if new_value is not None and getattr(user, field) != new_value:
                changes[field] = {"from": getattr(user, field), "to": new_value}
                setattr(user, field, new_value)
        if changes:
            if payload.role is not None:
                await self._sync_user_role(user.id, tenant_id, payload.role)
            await self.db.commit()
            await self.db.refresh(user)
            logger.info(
                "superadmin.admin.updated id=%s tenant=%s changes=%s",
                user_id, tenant_id, list(changes.keys()),
            )
        return user

    async def deactivate_admin(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Soft-delete: set is_active=false. Reversible from the same UI."""
        user = await self._get_user_in_tenant(tenant_id, user_id)
        if user.role == "superadmin":
            raise ValueError(
                "Cannot deactivate a superadmin via this endpoint. "
                "Use direct DB access for that — it's a privilege-escalation guard."
            )
        user.is_active = False
        user.status = "inactive"
        await self.db.commit()
        logger.info(
            "superadmin.admin.deactivated id=%s tenant=%s", user_id, tenant_id
        )

    # ── Helpers ────────────────────────────────────────────────────

    async def _find_existing_user(
        self, tenant_id: uuid.UUID, payload: AdminCreate
    ) -> User | None:
        if payload.email:
            result = await self.db.execute(
                select(User).where(
                    User.tenant_id == tenant_id, User.email == payload.email
                )
            )
            return result.scalar_one_or_none()
        if payload.telegram_id:
            result = await self.db.execute(
                select(User).where(
                    User.tenant_id == tenant_id, User.telegram_id == payload.telegram_id
                )
            )
            return result.scalar_one_or_none()
        return None

    async def _get_user_in_tenant(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self.db.get(User, user_id)
        if user is None or user.tenant_id != tenant_id:
            raise LookupError(f"User {user_id} not found in tenant {tenant_id}")
        return user
