"""Document catalog ORM integrity contracts."""

from uuid import uuid4

from fastapi.routing import APIRoute
from sqlalchemy.dialects import postgresql

from app.models.document import Document
from app.modules.documents.router import router as documents_router
from app.modules.documents.schemas import DocumentResponse
from app.modules.documents.service import CatalogFilters, list_catalog


def test_document_model_declares_catalog_constraints_and_indexes() -> None:
    constraint_names = {constraint.name for constraint in Document.__table__.constraints if constraint.name}
    index_names = {index.name for index in Document.__table__.indexes}

    assert {
        "ck_documents_index_status",
        "ck_documents_version_positive",
        "ck_documents_index_revision_positive",
        "ck_documents_index_chunks_nonnegative",
        "ck_documents_index_chunks_order",
    } <= constraint_names
    assert {
        "ix_documents_tenant_category_created_id",
        "ix_documents_tenant_lifecycle_created_id",
    } <= index_names


def test_nullable_hash_has_no_unique_or_not_null_contract() -> None:
    hash_column = Document.__table__.c.content_sha256

    assert hash_column.nullable is True
    assert not any(
        constraint.name and "content_sha256" in constraint.name and "unique" in constraint.name
        for constraint in Document.__table__.constraints
    )


def test_public_document_dto_and_upload_route_are_fail_closed() -> None:
    assert {"tenant_id", "uploaded_by", "s3_key"}.isdisjoint(DocumentResponse.model_fields)

    upload_route = next(
        route
        for route in documents_router.routes
        if isinstance(route, APIRoute) and route.path == "/documents/upload" and "POST" in route.methods
    )
    role_dependency = next(
        dependency.call
        for dependency in upload_route.dependant.dependencies
        if dependency.call and dependency.call.__name__ == "role_checker"
    )
    closure_values = [cell.cell_contents for cell in (role_dependency.__closure__ or ())]
    assert ("methodologist",) in closure_values


async def test_latest_subquery_uses_requested_lifecycle_scope() -> None:
    class EmptyResult:
        def all(self):
            return []

    class CapturingDB:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    db = CapturingDB()
    await list_catalog(
        db,
        uuid4(),
        CatalogFilters(lifecycle_status="delete_failed"),
    )
    sql = str(
        db.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "documents_1.lifecycle_status = 'delete_failed'" in sql
