from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.courses.router import _hydrate_course_authors


@pytest.mark.asyncio
async def test_catalog_authors_use_one_tenant_filtered_query_without_contact_data():
    tenant, author, unknown = uuid4(), uuid4(), uuid4()
    courses = [SimpleNamespace(created_by=author), SimpleNamespace(created_by=author),
               SimpleNamespace(created_by=unknown), SimpleNamespace(created_by=None)]
    result = SimpleNamespace(all=lambda: [SimpleNamespace(id=author, first_name=' Test ', last_name='Author')])
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    await _hydrate_course_authors(db, courses, tenant)
    assert [c.author_name for c in courses] == ['Test Author', 'Test Author', None, None]
    db.execute.assert_awaited_once()
    query = db.execute.call_args.args[0].compile()
    assert 'users.tenant_id =' in str(query) and tenant in query.params.values()
    assert set(next(v for v in query.params.values() if isinstance(v, list))) == {author, unknown}
    assert 'users.email' not in str(query) and 'password' not in str(query)


@pytest.mark.asyncio
async def test_legacy_courses_without_creator_do_not_issue_user_queries():
    course = SimpleNamespace(created_by=None)
    db = SimpleNamespace(execute=AsyncMock())
    await _hydrate_course_authors(db, [course], uuid4())
    db.execute.assert_not_awaited()
    assert course.author_name is None
