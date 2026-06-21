# ADR-0003: Multi-tenancy

**Дата:** 2026-06-21 · **Статус:** Accepted

## Контекст

Kamilya — multi-tenant SaaS. LMS модуль должен изолировать данные между тенантами. Любая утечка — критический инцидент (потеря доверия, GDPR/152-ФЗ штрафы).

## Решение

**Shared database, shared schema, row-level isolation.**

Все таблицы LMS содержат `tenant_id UUID NOT NULL`. Изоляция enforced на 3 уровнях:

### 1. ORM Level (Primary)
- SQLAlchemy middleware (или Drizzle middleware) автоматически подставляет `tenant_id = current_tenant_id` в каждый WHERE
- Прямой SQL запрещён — только через ORM/repository layer
- Code review: запрещены "ad-hoc" queries без tenant filter

### 2. Database Level (Defense in Depth)
- PostgreSQL Row-Level Security policies на все tenant-scoped таблицы
- `current_setting('app.tenant_id')` устанавливается через session variable
- Даже если ORM bug, RLS блокирует cross-tenant access

```sql
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
CREATE POLICY courses_tenant_isolation ON courses
  USING (tenant_id = current_setting('app.tenant_id', true)::UUID);
```

### 3. API Level (Validation)
- JWT содержит `tenant_id` claim
- Middleware проверяет что path/body не пытается cross-reference другой tenant
- Суперадмин использует отдельный `X-Superadmin-Override` header + audit log

## Обоснование

| Альтернатива | Почему отвергли |
|--------------|-----------------|
| **Database per tenant** | Provisioning overhead, миграции × N, $$$, JOIN cross-tenant невозможен |
| **Schema per tenant** | Тот же overhead, меньше изоляции чем DB per tenant |
| **Row-level only ORM** (без RLS) | Single point of failure — баг в middleware = утечка. RLS — defense in depth |
| **Row-level only DB** (без ORM middleware) | Неудобно для JOIN, manual `SET app.tenant_id` в каждой connection |

## Реализация

### Backend (SQLAlchemy)

```python
# app/core/db.py
from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria

class TenantSessionMiddleware:
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id

    async def __call__(self, request: Request, call_next):
        # Set PostgreSQL session variable
        await request.state.db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(self.tenant_id)}
        )
        return await call_next(request)

# Auto-apply to all queries
@event.listens_for(Session, "do_orm_execute")
def filter_by_tenant(state):
    if not state.is_select: return
    for entity in state.statement.column_descriptions:
        if hasattr(entity['entity'], 'tenant_id'):
            state.statement = state.statement.where(
                entity['entity'].tenant_id == current_tenant_id
            )
```

### Backend (FastAPI dependency)

```python
async def get_db_with_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    tenant_id = get_tenant_from_jwt(request)
    await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
    return db
```

### Superadmin Override

```python
async def get_db_with_optional_superadmin(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if request.headers.get("X-Superadmin-Override"):
        # Don't set tenant_id, allow global access
        await db.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        # Audit log
        await audit_log("superadmin.override", user=get_user(request))
    else:
        tenant_id = get_tenant_from_jwt(request)
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
    return db
```

## Тестирование

- **Unit:** каждый query тестируется с разными `tenant_id` → cross-tenant access должен fail
- **Integration:** реальный Postgres с RLS, пытаемся обойти → должно блокироваться
- **E2E:** два tenant'а, user A пытается читать tenant B's data → 404/403

## Миграция с Chamilo

Chamilo не имеет RLS. При импорте данных:
1. Сначала `INSERT` без tenant_id
2. Потом backfill `tenant_id` из source
3. Затем `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`

## Последствия

- Все queries чуть медленнее (RLS overhead ~5-10%) — acceptable
- Миграции сложнее (нужно тестировать что RLS не ломается)
- Read replicas: RLS policy наследуется автоматически
- Disaster recovery: backup восстанавливает RLS state вместе с данными

**Принято:** 2026-06-21
