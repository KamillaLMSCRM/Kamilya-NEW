"""Contract tests for the Kazakhstan compliance blueprint catalogue."""

import pytest

from app.modules.courses.blueprint_catalog import get_blueprint
from app.modules.courses.blueprint_service import calculate_adaptation, get_catalog

BLUEPRINT_IDS = (
    "kz-information-security-awareness",
    "kz-finance-information-security",
    "kz-occupational-safety-induction",
    "kz-fire-safety-instruction",
)


@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_compliance_catalog_has_four_stable_localized_blueprints(locale: str) -> None:
    items = get_catalog(locale)

    assert len(items) == len(BLUEPRINT_IDS)
    assert {item.id for item in items} == set(BLUEPRINT_IDS)
    assert len({item.id for item in items}) == 4
    assert {item.locale for item in items} == {locale}

    for item in items:
        payload = item.model_dump()
        assert payload["compliance_mode"] in {"lms_only", "blended", "external_certified"}
        assert payload["applicability"]
        assert payload["tags"]
        assert payload["legal_basis"]
        assert "base_blueprint_id" in payload
        assert payload["checklist"]
        assert all(checklist_item["title"] for checklist_item in payload["checklist"])
        assert all(checklist_item["answer_placeholder"] for checklist_item in payload["checklist"])
        assert all(checklist_item["example_answer"] for checklist_item in payload["checklist"])
        assert all(
            checklist_item["example_answer"] != checklist_item["answer_placeholder"]
            for checklist_item in payload["checklist"]
        )


def test_finance_overlay_has_universal_base_without_id_collision() -> None:
    universal = get_blueprint("ru", blueprint_id="kz-information-security-awareness")
    finance = get_blueprint("ru", blueprint_id="kz-finance-information-security")

    assert universal["base_blueprint_id"] is None
    assert finance["base_blueprint_id"] == universal["id"]
    assert finance["id"] != finance["base_blueprint_id"]
    assert finance["id"] in BLUEPRINT_IDS


@pytest.mark.parametrize(
    "blueprint_id",
    [
        "kz-occupational-safety-induction",
        "kz-fire-safety-instruction",
    ],
)
def test_practical_and_workplace_gates_are_explicit(blueprint_id: str) -> None:
    for locale in ("ru", "kk"):
        blueprint = get_blueprint(locale, blueprint_id=blueprint_id)
        text = " ".join(blueprint["limitations"]).lower()

        assert any(token in text for token in ("практи", "workplace", "практик", "жұмыс ор"))
        assert any(token in text for token in ("рабоч", "workplace", "жұмыс ор", "өндір"))


def test_readiness_requires_every_required_tenant_answer() -> None:
    blueprint = get_blueprint("ru", blueprint_id="kz-fire-safety-instruction")

    readiness, completed, missing = calculate_adaptation(blueprint, {})
    assert readiness < 100
    assert completed == []
    assert missing == [item["id"] for item in blueprint["checklist"] if item["required"]]

    answers = {item["id"]: f"Tenant rule for {item['id']}" for item in blueprint["checklist"]}
    readiness, completed, missing = calculate_adaptation(blueprint, answers)
    assert readiness == 100
    assert completed == [item["id"] for item in blueprint["checklist"]]
    assert missing == []
