"""Training log module — единый журнал обучения для HR/admin.

P0.3 first-tenant hardening.

Что здесь:
- `GET /api/v1/admin/training-log` — список строк «сотрудник × курс» с фильтрами
  и CSV-экспортом.
- Native и SCORM курсы в одном журнале (вычисляем по `courses.delivery_type`).
- Tenant scope строго из JWT.
- Никакого N+1: один SELECT с JOIN'ами + пара агрегатов.
"""

__all__ = ["router"]