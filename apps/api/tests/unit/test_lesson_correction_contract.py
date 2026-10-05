"""Correction admission policy tests: no database, network or real provider."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.editor_assistant.patch_contract import (
    PatchApplicabilityStatus,
    PatchContractError,
    PatchOperation,
    PatchOperationType,
    ProviderProvenance,
    SourceEvidenceReference,
    StructuredEditPatch,
    ValidationReport,
    ValidationStatus,
)
from app.modules.methodologist_workbench.correction_contract import (
    CorrectionError,
    LessonCorrectionContext,
    LessonCorrectionSnapshot,
    prepare_lesson_correction,
    preview_lesson_correction,
)
from app.modules.methodologist_workbench.plan_contract import ActorContext, ConfirmationRequest

NOW = datetime(2026, 10, 5, 8, tzinfo=UTC)
TENANT, ACTOR, COURSE, MODULE, LESSON, DOCUMENT, PLAN = [UUID(int=index) for index in range(1, 8)]
BEFORE = "Перед работой проверьте исправность оборудования."
AFTER = "Перед началом работы убедитесь, что оборудование исправно."


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def context(**changes):
    values = {
        "tenant_id": TENANT,
        "course_id": COURSE,
        "module_id": MODULE,
        "lesson_id": LESSON,
        "course_version": "course-v4",
        "lesson_version": "lesson-v2",
        "lifecycle": "draft",
        "content": BEFORE,
        "sources": [
            {
                "document_id": DOCUMENT,
                "version": 2,
                "content_sha256": "a" * 64,
                "index_revision": 3,
                "evidence": [{"locator": "chunk:4", "evidence_hash": "b" * 64}],
            }
        ],
    }
    values.update(changes)
    return LessonCorrectionContext.model_validate(values)


def snapshot(**changes):
    values = {
        "plan_id": PLAN,
        "revision": 1,
        "actor_id": ACTOR,
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "context": context(),
        "instruction": "Упростить формулировку, сохранив смысл.",
        "locale": "ru",
    }
    values.update(changes)
    return LessonCorrectionSnapshot.model_validate(values)


def actor(**changes):
    return ActorContext(
        tenant_id=changes.get("tenant_id", TENANT),
        actor_id=changes.get("actor_id", ACTOR),
        active_role=changes.get("active_role", "methodologist"),
    )


class FakeProvider:
    def __init__(self, transform=lambda patch: patch):
        self.calls = 0
        self.transform = transform
        self.command = None

    def propose_patch(self, command):
        self.calls += 1
        self.command = command
        patch = StructuredEditPatch(
            request_key=command.request_key,
            preview_key=command.preview_key,
            target=command.target,
            base_snapshot=command.base_snapshot,
            operations=(
                PatchOperation(
                    target=command.target,
                    field_path="lesson.content",
                    operation=PatchOperationType.REPLACE,
                    before_value=BEFORE,
                    before_hash=digest(BEFORE),
                    after_value=AFTER,
                    after_hash=digest(AFTER),
                ),
            ),
            source_evidence=(SourceEvidenceReference(str(DOCUMENT), "chunk:4", "b" * 64),),
            validation_report=ValidationReport(ValidationStatus.PASS),
            provider_provenance=ProviderProvenance("fake.test", "fake-v1", "correction-v1", "test-v1"),
            applicability_status=PatchApplicabilityStatus.APPLICABLE,
        )
        return self.transform(patch)


def make_preview(plan=None, provider=None):
    plan = plan or snapshot()
    return preview_lesson_correction(
        plan, actor=actor(), current=plan.context, provider=provider or FakeProvider(), now=NOW
    )


def confirm(preview, **changes):
    values = {
        "plan_id": preview.snapshot.plan_id,
        "revision": preview.snapshot.revision,
        "fingerprint": preview.fingerprint,
    }
    values.update(changes)
    return ConfirmationRequest(**values)


def prepare(preview, request=None, **changes):
    return prepare_lesson_correction(
        preview,
        request or confirm(preview),
        actor=changes.get("actor", actor()),
        current=changes.get("current", preview.snapshot.context),
        now=changes.get("now", NOW),
    )


def test_exact_diff_and_repeated_confirmation_are_pure_not_execution():
    plan = snapshot()
    provider = FakeProvider()
    original = plan.model_dump(mode="json")
    preview = make_preview(plan, provider)
    application = prepare(preview)
    assert application == prepare(preview)
    assert application.destination == "current_draft"
    assert application.new_draft_revision_id is None
    assert application.patch.operations[0].before_value == BEFORE
    assert application.patch.operations[0].after_value == AFTER
    assert plan.model_dump(mode="json") == original
    assert provider.calls == 1
    with pytest.raises(FrozenInstanceError):
        preview.fingerprint = "c" * 64


@pytest.mark.parametrize("locale", ["ru", "kk", "en"])
def test_locale_is_preserved_without_hardcoded_russian(locale):
    provider = FakeProvider()
    make_preview(snapshot(locale=locale), provider)
    assert provider.command.locale == locale


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"tenant_id": uuid4()}, "context_mismatch"),
        ({"actor_id": uuid4()}, "context_mismatch"),
        ({"active_role": "admin"}, "role_denied"),
        ({"active_role": "superadmin"}, "role_denied"),
        ({"active_role": "student"}, "role_denied"),
    ],
)
def test_owner_and_active_role_denial_happens_before_provider_and_confirmation(changes, code):
    provider = FakeProvider()
    plan = snapshot()
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        preview_lesson_correction(plan, actor=actor(**changes), current=plan.context, provider=provider, now=NOW)
    assert provider.calls == 0
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        prepare(make_preview(), actor=actor(**changes))


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", uuid4()),
        ("course_id", uuid4()),
        ("module_id", uuid4()),
        ("lesson_id", uuid4()),
        ("course_version", "course-v5"),
        ("lesson_version", "lesson-v3"),
        ("content", BEFORE + " Новый текст."),
        ("lifecycle", "published"),
    ],
)
def test_changed_target_course_approval_version_or_text_is_stale(field, value):
    plan = snapshot()
    current = context(**{field: value})
    provider = FakeProvider()
    with pytest.raises(CorrectionError, match="^stale$"):
        preview_lesson_correction(plan, actor=actor(), current=current, provider=provider, now=NOW)
    assert provider.calls == 0
    with pytest.raises(CorrectionError, match="^stale$"):
        prepare(make_preview(plan), current=current)


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_id", uuid4()),
        ("version", 3),
        ("content_sha256", "c" * 64),
        ("index_revision", 4),
        ("evidence", [{"locator": "chunk:5", "evidence_hash": "b" * 64}]),
        ("evidence", [{"locator": "chunk:4", "evidence_hash": "c" * 64}]),
    ],
)
def test_changed_source_or_exact_evidence_refuses_confirmation(field, value):
    current = context().model_dump()
    source = dict(current["sources"][0])
    source[field] = value
    current["sources"] = [source]
    with pytest.raises(CorrectionError, match="^stale$"):
        prepare(make_preview(), current=LessonCorrectionContext.model_validate(current))


@pytest.mark.parametrize(
    "time,code",
    [
        (NOW - timedelta(seconds=1), "preview_not_yet_valid"),
        (NOW + timedelta(minutes=15), "expired"),
        (NOW.replace(tzinfo=None), "invalid_confirmation_time"),
    ],
)
def test_time_bounds_before_provider_and_apply(time, code):
    plan, provider = snapshot(), FakeProvider()
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        preview_lesson_correction(plan, actor=actor(), current=plan.context, provider=provider, now=time)
    assert provider.calls == 0
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        prepare(make_preview(), now=time)


def test_published_content_cannot_be_proposed_or_overwritten_by_this_slice():
    plan, provider = snapshot(context=context(lifecycle="published")), FakeProvider()
    with pytest.raises(CorrectionError, match="^new_draft_required$"):
        preview_lesson_correction(plan, actor=actor(), current=plan.context, provider=provider, now=NOW)
    assert provider.calls == 0


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"plan_id": uuid4()}, "plan_mismatch"),
        ({"revision": 2}, "revision_mismatch"),
        ({"fingerprint": "d" * 64}, "fingerprint_mismatch"),
    ],
)
def test_confirmation_binds_exact_preview(changes, code):
    preview = make_preview()
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        prepare(preview, confirm(preview, **changes))


@pytest.mark.parametrize(
    "change",
    [
        {"before_value": "Other text"},
        {"before_hash": "c" * 64},
        {"after_hash": "c" * 64},
        {"after_value": " "},
        {"after_value": "x" * 64_001},
        {"after_value": {"content": AFTER}},
        {"after_value": BEFORE, "after_hash": digest(BEFORE)},
    ],
)
def test_before_after_payload_and_digests_are_verified(change):
    provider = FakeProvider(lambda patch: replace(patch, operations=(replace(patch.operations[0], **change),)))
    with pytest.raises(CorrectionError, match="^invalid_content_change$"):
        make_preview(provider=provider)


@pytest.mark.parametrize(
    "transform",
    [
        lambda patch: replace(patch, operations=(replace(patch.operations[0], field_path="lesson.title"),)),
        lambda patch: replace(patch, operations=(replace(patch.operations[0], operation=PatchOperationType.APPEND),)),
        lambda patch: replace(patch, operations=patch.operations * 2),
        lambda patch: replace(patch, source_evidence=()),
        lambda patch: replace(patch, applicability_status=PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION),
    ],
)
def test_generic_editor_scope_and_validation_are_reused(transform):
    with pytest.raises(CorrectionError, match="^invalid_proposal$"):
        make_preview(provider=FakeProvider(transform))


@pytest.mark.parametrize(
    "evidence",
    [
        (SourceEvidenceReference(str(uuid4()), "chunk:4", "b" * 64),),
        (SourceEvidenceReference(str(DOCUMENT), "chunk:5", "b" * 64),),
        (SourceEvidenceReference(str(DOCUMENT), "chunk:4", "c" * 64),),
        (SourceEvidenceReference(str(DOCUMENT), "chunk:4"),),
        (SourceEvidenceReference(str(DOCUMENT), "chunk:4", "b" * 64),) * 2,
    ],
)
def test_invented_cross_source_missing_hash_or_duplicate_evidence_is_refused(evidence):
    with pytest.raises(CorrectionError, match="^invalid_source_evidence$"):
        make_preview(provider=FakeProvider(lambda patch: replace(patch, source_evidence=evidence)))


def test_another_valid_after_text_cannot_replace_a_confirmed_preview():
    preview = make_preview()
    changed = AFTER + " Дополнение."
    patch = replace(
        preview.patch,
        operations=(replace(preview.patch.operations[0], after_value=changed, after_hash=digest(changed)),),
    )
    with pytest.raises(CorrectionError, match="^fingerprint_mismatch$"):
        prepare(replace(preview, patch=patch))


@pytest.mark.parametrize(
    "field,value",
    [
        ("instruction", "Другое поручение"),
        ("locale", "kk"),
        ("actor_id", uuid4()),
    ],
)
def test_seal_binds_instruction_locale_and_owner(field, value):
    original = make_preview()
    changed = make_preview(snapshot(**{field: value})) if field != "actor_id" else None
    if changed:
        assert changed.fingerprint != original.fingerprint
    else:
        with pytest.raises(CorrectionError, match="^context_mismatch$"):
            make_preview(snapshot(**{field: value}))


@pytest.mark.parametrize(
    "exception,code",
    [
        (RuntimeError("private source or provider token"), "proposal_unavailable"),
        (PatchContractError("private source or provider token"), "invalid_proposal"),
    ],
)
def test_provider_exception_text_is_not_reflected(exception, code):
    def fail(patch):
        raise exception

    with pytest.raises(CorrectionError) as captured:
        make_preview(provider=FakeProvider(fail))
    assert str(captured.value) == code
    assert captured.value.__suppress_context__


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": NOW},
        {"expires_at": NOW + timedelta(minutes=16)},
        {"created_at": NOW.replace(tzinfo=None)},
        {"locale": "auto"},
        {"instruction": " "},
        {"revision": True},
        {"context": context().model_dump() | {"content": " "}},
        {"context": context().model_dump() | {"lesson_version": "v" * 121}},
    ],
)
def test_snapshot_is_strict_and_bounded(changes):
    with pytest.raises(ValidationError):
        snapshot(**changes)


def test_duplicate_source_and_evidence_identity_is_rejected():
    source = context().model_dump()["sources"][0]
    with pytest.raises(ValidationError):
        context(sources=[source, source])
    with pytest.raises(ValidationError):
        context(sources=[source | {"evidence": source["evidence"] * 2}])


def test_valid_multi_source_evidence_is_admitted_and_preserved_in_apply_plan():
    second_id = UUID(int=8)
    first_source = context().model_dump()["sources"][0]
    second_source = first_source | {"document_id": second_id, "content_sha256": "c" * 64}
    plan = snapshot(context=context(sources=[first_source, second_source]))
    second_reference = SourceEvidenceReference(str(second_id), "chunk:4", "b" * 64)
    provider = FakeProvider(lambda patch: replace(patch, source_evidence=patch.source_evidence + (second_reference,)))
    preview = make_preview(plan, provider)
    assert len(prepare(preview).patch.source_evidence) == 2
    assert preview.snapshot.context.sources[1].document_id == second_id


def test_forged_applicability_is_revalidated_at_confirmation():
    preview = make_preview()
    forged = replace(preview.patch, applicability_status=PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION)
    with pytest.raises(CorrectionError, match="^invalid_proposal$"):
        prepare(replace(preview, patch=forged))


def test_total_evidence_budget_is_enforced_across_sources():
    first_source = context().model_dump()["sources"][0]
    evidence = [{"locator": f"chunk:{index}", "evidence_hash": "b" * 64} for index in range(33)]
    with pytest.raises(ValidationError):
        context(
            sources=[
                first_source | {"evidence": evidence},
                first_source | {"document_id": UUID(int=8), "evidence": evidence},
            ]
        )
