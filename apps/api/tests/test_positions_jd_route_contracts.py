"""Route-contract tests for the job-description workflow.

The positions feature is split across three APIRouter instances.  A stray
stacked decorator can therefore register a valid URL against the wrong
handler while FastAPI still starts successfully.  These assertions keep the
public JD endpoints unique and bound to the intended function.
"""

from fastapi.routing import APIRoute

from app.modules.positions.jd_router import router as jd_router
from app.modules.positions.recommendations_router import router as recommendations_router
from app.modules.positions.router import router as positions_router


def _handlers(path: str, method: str) -> list[str]:
    routes = [
        *positions_router.routes,
        *jd_router.routes,
        *recommendations_router.routes,
    ]
    return [
        route.endpoint.__name__
        for route in routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    ]


def test_job_description_routes_have_one_intended_handler_each() -> None:
    expected = {
        ("/positions/analyze-jd", "POST"): "analyze_jd",
        ("/positions/bulk-analyze-jd", "POST"): "bulk_analyze_jd",
        ("/positions/generate-jd-from-name", "POST"): "generate_jd_from_name",
        ("/positions/bulk-create", "POST"): "bulk_create_positions",
        ("/positions/{position_id}/suggest-courses", "POST"): "suggest_courses",
        ("/positions/{position_id}/create-courses", "POST"): "create_courses_from_suggestions",
        ("/positions/{position_id}/instruction", "POST"): "upload_position_instruction",
        (
            "/positions/{position_id}/generate-instruction-course",
            "POST",
        ): "generate_instruction_course",
    }

    for (path, method), endpoint_name in expected.items():
        assert _handlers(path, method) == [endpoint_name], (path, method)


def test_positions_routes_require_learning_content_role() -> None:
    routes = [
        *positions_router.routes,
        *jd_router.routes,
        *recommendations_router.routes,
    ]

    for route in routes:
        if not isinstance(route, APIRoute):
            continue

        role_dependencies = [
            dependency.dependency
            for dependency in route.dependencies
            if dependency.dependency.__name__ == "role_checker"
        ]
        assert len(role_dependencies) == 1, route.path

        closure_values = [
            cell.cell_contents
            for cell in (role_dependencies[0].__closure__ or ())
        ]
        assert (
            "superadmin",
            "methodologist",
            "teacher",
        ) in closure_values, route.path
