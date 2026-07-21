"""User management service"""
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from argon2 import PasswordHasher

from app.models.users import User
from app.models.user_roles import UserRole

ph = PasswordHasher()

# Roles visible on the team-management surface (ADR-0011).
# Students are auto-provisioned via Telegram/kiosk and not managed here.
TEAM_ROLES = ("methodologist", "admin", "org_admin")


async def list_users(
    db: AsyncSession,
    tenant_id: UUID,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    """List users with pagination and filters.

    role='non_student' is a sentinel meaning "all team roles,
    excluding student" (the default for /v1/users per ADR-0011).
    """
    query = select(User).where(User.tenant_id == tenant_id)
    count_query = select(func.count(User.id)).where(User.tenant_id == tenant_id)

    if search:
        search_filter = (
            User.email.ilike(f"%{search}%") |
            User.first_name.ilike(f"%{search}%") |
            User.last_name.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if role == "non_student":
        # Default surface — show only team-managed roles.
        query = query.where(User.role.in_(TEAM_ROLES))
        count_query = count_query.where(User.role.in_(TEAM_ROLES))
    elif role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)

    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(desc(User.created_at)).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    return users, total


async def get_user(db: AsyncSession, user_id: UUID, tenant_id: UUID) -> User | None:
    """Get a specific user."""
    user = await db.get(User, user_id)
    if user and user.tenant_id == tenant_id:
        return user
    return None


async def get_role_map(
    db: AsyncSession, users: list[User], tenant_id: UUID
) -> dict[UUID, list[str]]:
    """Load all role assignments for a page of users in one query."""
    if not users:
        return {}
    result = await db.execute(
        select(UserRole.user_id, UserRole.role).where(
            UserRole.tenant_id == tenant_id,
            UserRole.user_id.in_([user.id for user in users]),
        )
    )
    role_map: dict[UUID, set[str]] = {user.id: {user.role} for user in users}
    for user_id, role in result.all():
        role_map.setdefault(user_id, set()).add(role)
    return {
        user.id: [user.role, *sorted(role_map[user.id] - {user.role})]
        for user in users
    }


async def assign_role(
    db: AsyncSession, user_id: UUID, tenant_id: UUID, role: str
) -> User | None:
    if role not in TEAM_ROLES:
        raise ValueError(f"Invalid team role: {role}")
    user = await get_user(db, user_id, tenant_id)
    if not user:
        return None
    existing = await db.execute(
        select(UserRole.id).where(
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id,
            UserRole.role == role,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("Role already assigned")
    db.add(UserRole(user_id=user_id, tenant_id=tenant_id, role=role))
    await db.flush()
    return user


async def create_user(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    first_name: str,
    last_name: str,
    role: str = "student",
    password: str = "",
    is_active: bool = True,
) -> User:
    """Create a new user."""
    # Check if email already exists
    existing = await db.execute(
        select(User).where(User.email == email, User.tenant_id == tenant_id)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Email already exists")

    hashed_password = ph.hash(password) if password else ""

    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=role,
        is_active=is_active,
        password_hash=hashed_password,
        status="active",
    )
    db.add(user)
    await db.flush()

    # Create role entry
    user_role = UserRole(
        id=uuid4(),
        user_id=user.id,
        tenant_id=tenant_id,
        role=role,
    )
    db.add(user_role)
    await db.flush()

    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    updates: dict,
) -> User | None:
    """Update a user."""
    user = await get_user(db, user_id, tenant_id)
    if not user:
        return None

    for field, value in updates.items():
        if value is not None and hasattr(user, field):
            setattr(user, field, value)

    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: UUID, tenant_id: UUID) -> bool:
    """Soft-delete a user (set is_active=False)."""
    user = await get_user(db, user_id, tenant_id)
    if not user:
        return False

    user.is_active = False
    await db.flush()
    return True


async def reset_password(
    db: AsyncSession, user_id: UUID, tenant_id: UUID, new_password: str
) -> bool:
    """Reset user password."""
    user = await get_user(db, user_id, tenant_id)
    if not user:
        return False

    user.password_hash = ph.hash(new_password)
    await db.flush()
    return True


async def change_role(
    db: AsyncSession, user_id: UUID, tenant_id: UUID, new_role: str
) -> User | None:
    """Change user role."""
    valid_roles = ["student", "methodologist", "admin", "org_admin"]
    if new_role not in valid_roles:
        raise ValueError(f"Invalid role. Must be one of: {valid_roles}")

    user = await get_user(db, user_id, tenant_id)
    if not user:
        return None

    user.role = new_role

    # Changing the primary role must not remove other assigned roles.
    existing_role = (await db.execute(
        select(UserRole.id).where(
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id,
            UserRole.role == new_role,
        )
    )).scalar_one_or_none()

    if existing_role is None:
        db.add(UserRole(
            id=uuid4(),
            user_id=user_id,
            tenant_id=tenant_id,
            role=new_role,
        ))

    await db.flush()
    await db.refresh(user)
    return user
