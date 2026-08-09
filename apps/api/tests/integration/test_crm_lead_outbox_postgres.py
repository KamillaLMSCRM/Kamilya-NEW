"""PostgreSQL contracts for atomic lead capture and delivery claims."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import exc, text

from app.core.db import async_session_factory


async def _insert_public_lead(email: str) -> UUID:
    async with async_session_factory() as session:
        lead_id = (
            await session.execute(
                text(
                    "SELECT insert_public_tenant_lead("
                    ":company, :contact, :email, NULL, '11', 'ru', "
                    "'demo', NULL, CAST(:metadata AS jsonb))"
                ),
                {
                    "company": "QA CRM Outbox",
                    "contact": "QA Operator",
                    "email": email,
                    "metadata": json.dumps({"industry": "finance"}),
                },
            )
        ).scalar_one()
        await session.commit()
        return lead_id


async def _cleanup_public_lead(lead_id: UUID) -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.is_superadmin', 'true', true)")
        )
        await session.execute(
            text("DELETE FROM tenant_leads WHERE id = :id"),
            {"id": lead_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_lead_and_outbox_roll_back_as_one_transaction():
    lead_id: UUID | None = None
    async with async_session_factory() as session:
        lead_id = (
            await session.execute(
                text(
                    "SELECT insert_public_tenant_lead("
                    ":company, :contact, :email, NULL, NULL, 'ru', "
                    "'demo', NULL, '{}'::jsonb)"
                ),
                {
                    "company": "QA Rollback",
                    "contact": "QA Operator",
                    "email": f"qa-crm-rollback-{uuid4().hex}@example.test",
                },
            )
        ).scalar_one()
        await session.rollback()

    async with async_session_factory() as check:
        claim = (
            await check.execute(
                text("SELECT * FROM crm_claim_lead_outbox(:id)"),
                {"id": lead_id},
            )
        ).mappings().one_or_none()
        assert claim is None
        await check.execute(
            text("SELECT set_config('app.is_superadmin', 'true', true)")
        )
        lead_count = (
            await check.execute(
                text("SELECT count(*) FROM tenant_leads WHERE id = :id"),
                {"id": lead_id},
            )
        ).scalar_one()
        assert lead_count == 0


@pytest.mark.asyncio
async def test_concurrent_delivery_claim_has_exactly_one_winner():
    lead_id = await _insert_public_lead(
        f"qa-crm-claim-{uuid4().hex}@example.test"
    )

    async def claim():
        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT * FROM crm_claim_lead_outbox(:id)"),
                    {"id": lead_id},
                )
            ).mappings().one_or_none()
            await session.commit()
            return row

    try:
        first, second = await asyncio.gather(claim(), claim())
        winners = [row for row in (first, second) if row is not None]
        assert len(winners) == 1
        winner = winners[0]
        assert winner["id"] == lead_id
        assert bytes(winner["payload_bytes"])

        async with async_session_factory() as session:
            finalized = (
                await session.execute(
                    text(
                        "SELECT crm_finalize_lead_outbox("
                        ":id, :token, 'defer', NULL, 'test_cleanup')"
                    ),
                    {"id": lead_id, "token": winner["claim_token"]},
                )
            ).scalar_one()
            await session.commit()
            assert finalized is True
    finally:
        await _cleanup_public_lead(lead_id)


@pytest.mark.asyncio
async def test_runtime_role_cannot_read_outbox_payload_table_directly():
    lead_id = await _insert_public_lead(
        f"qa-crm-rls-{uuid4().hex}@example.test"
    )

    try:
        async with async_session_factory() as session:
            with pytest.raises(exc.ProgrammingError):
                await session.execute(
                    text(
                        "SELECT payload_bytes FROM crm_lead_outbox "
                        "WHERE id = :id"
                    ),
                    {"id": lead_id},
                )
            await session.rollback()

        async with async_session_factory() as session:
            claimed = (
                await session.execute(
                    text("SELECT * FROM crm_claim_lead_outbox(:id)"),
                    {"id": lead_id},
                )
            ).mappings().one()
            assert claimed["id"] == lead_id
            await session.execute(
                text(
                    "SELECT crm_finalize_lead_outbox("
                    ":id, :token, 'defer', NULL, 'test_cleanup')"
                ),
                {"id": lead_id, "token": claimed["claim_token"]},
            )
            await session.commit()
    finally:
        await _cleanup_public_lead(lead_id)
