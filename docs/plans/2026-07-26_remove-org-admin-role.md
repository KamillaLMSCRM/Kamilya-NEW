# Удаление дублирующей роли `org_admin`

## Цель

Оставить единственную административную роль тенанта `admin`. Роль
`org_admin` не имеет отдельной зоны ответственности или набора прав и не должна
отображаться, назначаться, сохраняться в БД либо приниматься backend.

## План

1. **Миграция данных и ограничений БД**
   - добавить Alembic-миграцию после `0073`;
   - заменить `users.role = 'org_admin'` на `admin`;
   - перенести записи `user_roles.role = 'org_admin'` в `admin` с безопасным
     устранением дублей;
   - пересоздать check constraints таблиц `users` и `user_roles` без
     `org_admin`;
   - предусмотреть обратимый downgrade только на уровне схемы, без
     восстановления искусственно удалённого различия ролей.

2. **Backend и RBAC**
   - удалить `org_admin` из канонического списка ролей, схем и сервисов;
   - заменить проверки `admin`/`org_admin` на `admin`;
   - убрать возможность назначать и impersonate роль `org_admin`;
   - обновить подсчёты системных пользователей и trial-лимитов;
   - обновить backend-тесты ролевых границ.

3. **Frontend и UX**
   - удалить `org_admin` из route registry, role switcher и форм команды;
   - удалить роль из superadmin-форм и invite labels;
   - обновить страницы с локальными role arrays;
   - удалить переводы и описания роли во всех локалях;
   - обновить frontend-тесты.

4. **Каноническая документация**
   - обновить `AGENTS.md`, `PROJECT.md`, `README.md`, `docs/CODEX_HANDOFF.md`,
     `docs/PROJECT-CONTEXT.md`, `docs/PROJECT_INTERNAL_DOCUMENTATION.md`;
   - актуализировать ADR-0011 и ADR-0012;
   - исторические отчёты и закрытые планы не переписывать.

5. **Проверка**
   - проверить единственную голову Alembic;
   - запустить целевые backend и frontend unit-тесты;
   - выполнить TypeScript/build-проверку;
   - проверить поиском, что `org_admin` остался только в самой миграции и
     исторических материалах;
   - проверить итоговый diff и чистоту рабочей копии.

## Отчёт о выполнении

### Пункт 1 — миграция данных и ограничений БД

**Что сделано:** добавлена миграция `0074_remove_org_admin_role.py`. Она
устраняет дубли `admin`/`org_admin` в `user_roles`, заменяет оставшиеся
`org_admin` на `admin` в `user_roles`, `users` и `user_invitations`, затем
пересоздаёт ограничения ролей без `org_admin`.

**Проверки:** логика миграции сохраняет уникальность
`(user_id, tenant_id, role)`; downgrade восстанавливает только допустимое
значение схемы и намеренно не пытается восстановить несуществующее продуктовое
различие.

**Статус:** готово.

### Пункт 2 — backend и RBAC

**Что сделано:** `org_admin` удалён из ORM constraints, канонического списка
JWT-ролей, `require_role`-проверок, team-role сервисов, trial-лимитов,
superadmin-схем, impersonation, kiosk/integration/certificate/admin API и
bootstrap SQL. Backend больше не принимает и не выдаёт эту роль.

**Проверки:** поиск по runtime-коду backend не находит `org_admin`; тесты
ролевых границ обновлены и отдельно фиксируют, что роль не входит в
`GRANTABLE_ROLES`.

**Статус:** готово.

### Пункт 3 — frontend и UX

**Что сделано:** роль удалена из typed route registry, переключателя рабочих
режимов, форм команды и superadmin, локальных role arrays, приглашений и
переводов RU/KK/EN. В team UI теперь доступны только `admin` и `methodologist`.

**Проверки:** JSON локалей успешно разбирается; поиск по frontend runtime и
тестам не находит `org_admin`.

**Статус:** готово.

### Пункт 4 — каноническая документация

**Что сделано:** обновлены entry-point документы проекта, внутреннее описание,
handoff, README, ADR-0011, ADR-0012, актуальный source-library design и
документация invitation flow. Исторические отчёты, закрытые планы и старые ТЗ
оставлены без переписывания.

**Проверки:** в канонических документах, runtime-коде и bootstrap SQL больше
нет упоминаний `org_admin`.

**Статус:** готово.

### Пункт 5 — проверка

**Что сделано:**

- Alembic: единственная голова `0074`; чистая локальная PostgreSQL 16 база
  успешно мигрирована с нуля до `head`;
- migration scenario: пользователь с одновременными `admin` и `org_admin`
  получил одну запись `admin`, пользователь только с `org_admin` был
  преобразован в `admin`, pending invitation также стала `admin`;
- constraint scenario: новая запись `org_admin` отклонена
  `ck_user_role_role`;
- backend: полный suite — `496 passed`;
- frontend: полный Vitest suite — `134 passed`;
- TypeScript: `tsc --noEmit` — успешно;
- production build: Next.js build — успешно, только ранее существовавшие
  lint-предупреждения;
- Python 3.12: `compileall` — успешно;
- scoped Ruff для новой миграции и нового role-contract теста — успешно;
- `git diff --check` — успешно;
- runtime/canonical search — упоминаний `org_admin` нет.

Полный repository-wide Ruff не является зелёным baseline: он находит
существующие до этой задачи нарушения в старом коде. В рамках изменённого
контракта новых Ruff-ошибок не осталось.

**Статус:** готово локально. Push и production deploy не выполнялись без
отдельного разрешения.
