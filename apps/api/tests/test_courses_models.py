"""Unit tests for courses module."""
import pytest

from app.modules.courses.schemas import CourseCreate, CourseUpdate, CourseResponse


class TestCourseSchemas:
    """Test course pydantic schemas."""

    def test_course_create_valid(self) -> None:
        """Test valid course creation schema."""
        course_data = CourseCreate(title="Test Course", description="Description")
        assert course_data.title == "Test Course"
        assert course_data.description == "Description"
        assert course_data.status == "draft"

    def test_course_create_empty_title(self) -> None:
        """Test course creation with empty title should fail."""
        with pytest.raises(Exception):
            CourseCreate(title="", description="Description")

    def test_course_update_partial(self) -> None:
        """Test partial update schema."""
        update = CourseUpdate(title="New Title")
        data = update.model_dump(exclude_unset=True)
        assert data == {"title": "New Title"}
        assert "description" not in data
        assert "status" not in data

    def test_course_response_required_fields(self) -> None:
        """CourseResponse validates from dict."""
        from uuid import uuid4
        from datetime import datetime
        data = {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "title": "Test",
            "description": "Desc",
            "status": "draft",
            "created_by": uuid4(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "published_at": None,
        }
        resp = CourseResponse(**data)
        assert resp.title == "Test"
        assert resp.status == "draft"
