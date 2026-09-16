from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.training_evidence.form_settings import (
    TrainingEvidenceFormSettings,
    get_training_evidence_form_settings,
    update_training_evidence_form_settings,
)


class _Database:
    def __init__(self, tenant):
        self.tenant = tenant
        self.flushed = False

    async def get(self, _model, _tenant_id):
        return self.tenant

    async def flush(self):
        self.flushed = True


@pytest.mark.asyncio
async def test_training_evidence_form_settings_default_to_tenant_identity():
    tenant = SimpleNamespace(name="ТОО Ломбард Сандык", settings={})

    settings = await get_training_evidence_form_settings(_Database(tenant), uuid4())

    assert settings.organization_name == "ТОО Ломбард Сандык"
    assert settings.title == "Подтверждение прохождения курса"
    assert "завершил" in settings.confirmation_text


@pytest.mark.asyncio
async def test_training_evidence_form_settings_are_saved_inside_tenant_settings(monkeypatch):
    tenant = SimpleNamespace(name="Tenant", settings={"unrelated": {"preserved": True}})
    db = _Database(tenant)
    monkeypatch.setattr("app.modules.training_evidence.form_settings.flag_modified", lambda *_args: None)
    payload = TrainingEvidenceFormSettings(
        organization_name="  ТОО Ломбард Сандык  ",
        representative_name="  Айжан Ахметова  ",
        representative_title="  Методист  ",
        footer_note="  Хранить в личном деле.  ",
    )

    result = await update_training_evidence_form_settings(db, uuid4(), payload)

    assert db.flushed is True
    assert tenant.settings["unrelated"] == {"preserved": True}
    assert tenant.settings["training_evidence_form_settings"]["organization_name"] == "ТОО Ломбард Сандык"
    assert result.representative_name == "Айжан Ахметова"
