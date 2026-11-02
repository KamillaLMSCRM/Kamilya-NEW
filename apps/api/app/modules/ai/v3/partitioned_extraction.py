"""Source-unit rule extraction with owned checkpoints; semantic review remains required."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.extraction_checkpoint import ExtractionJournal, build_extraction_identity, extract_once
from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity
from app.modules.ai.v3.prompts import RULE_EXTRACTION_SYSTEM_PROMPT
from app.modules.ai.v3.source_units import (
    SourceUnit,
    coalesce_leading_context,
    coalesce_structural_prose,
    coalesce_table_headers,
    find_rendered_quote_spans,
    plan_source_units,
    rendered_candidate_preserves_table_boundaries,
    source_section_label,
    source_table_topic,
)
from app.modules.ai.v3.validator import normalize_literal_quote


def _unit_family_ids(units: Sequence[SourceUnit], source_text: str) -> list[str]:
    """Attach an explicit table introduction and marked footnote to its table.

    The colon and escaped star are structural evidence, not inferred semantic
    equivalence. Rows in other documents, tables or sections stay separate.
    """
    families = [unit.container_id for unit in units]
    for index, unit in enumerate(units):
        if unit.kind != "table_row" or not unit.container_id:
            continue
        current_section = source_section_label(source_text, unit)
        if index and units[index - 1].kind == "prose":
            previous = units[index - 1]
            if (previous.end == unit.start and previous.text.rstrip().endswith(":")
                    and source_section_label(source_text, previous) == current_section):
                families[index - 1] = unit.container_id
        if index + 1 < len(units) and units[index + 1].kind == "prose":
            following = units[index + 1]
            marked = following.text.lstrip().startswith(("*\\*", "\\*"))
            if (unit.end == following.start and marked
                    and source_section_label(source_text, following) == current_section):
                families[index + 1] = unit.container_id
    return families


async def extract_partitioned_rule_model(
    corpus: DirectSourceCorpus,
    journal: ExtractionJournal,
    route_fingerprint: str,
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    cancellation_callback: Callable[[], Awaitable[None]] | None = None,
    *, direct_client: Any = None, direct_max_output_tokens: int = 8192,
    structured_output: bool = False,
) -> tuple[DocumentRuleModel, list[str]]:
    """Extract exact source units. Context is navigational, never coverage proof."""
    if not corpus.documents or any(doc.source_text is None or not doc.source_revision for doc in corpus.documents):
        raise ValueError("v3_partitioned_source_text_missing")
    if journal.tenant_id != corpus.tenant_id:
        raise ValueError("v3_partitioned_tenant_mismatch")

    rules: list[RuleEntity] = []
    warnings: list[str] = []
    source_texts: list[str] = []
    for doc_index, doc in enumerate(corpus.documents, 1):
        assert doc.source_text is not None
        source_texts.append(doc.source_text)
        units = coalesce_table_headers(plan_source_units(doc.source_text), doc.source_text)
        units = coalesce_leading_context(coalesce_structural_prose(units, doc.source_text), doc.source_text)
        if "".join(unit.text for unit in units) != doc.source_text:
            raise ValueError("v3_partitioned_source_inventory_invalid")
        if sum(bool(unit.text.strip()) for unit in units) > 1:
            warnings.append(f"Документ {doc.doc_id}: требуется проверить смысловые связи между фрагментами")
        family_ids = _unit_family_ids(units, doc.source_text)
        for index, unit in enumerate(units):
            if not unit.text.strip():
                continue
            if cancellation_callback:
                await cancellation_callback()
            context_parts = [unit.context]
            if index:
                context_parts.append("ПРЕДЫДУЩИЙ ФРАГМЕНТ:\n" + units[index - 1].text)
            if index + 1 < len(units):
                context_parts.append("СЛЕДУЮЩИЙ ФРАГМЕНТ:\n" + units[index + 1].text)
            context = "\n\n".join(part for part in context_parts if part)
            messages = [
                {"role": "system", "content": RULE_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"ДОКУМЕНТ: {doc.title}\n"
                    "Извлекай правила только из целевого фрагмента. Соседний контекст дан для понимания; "
                    "не выдавай его как самостоятельные правила. Сохраняй ссылки, условия и исключения.\n\n"
                    f"СОСЕДНИЙ КОНТЕКСТ:\n{context}\n\nЦЕЛЕВОЙ ФРАГМЕНТ:\n{unit.text}"
                )},
            ]
            from app.modules.ai.v3.extraction_response_schema import rule_extraction_response_format
            response_format = rule_extraction_response_format() if structured_output else {"type": "json_object"}
            identity = build_extraction_identity(
                tenant_id=corpus.tenant_id, job_id=journal.job_id, document_id=doc.doc_id,
                source_revision=doc.source_revision, source_text=doc.source_text, unit=unit,
                context=context, messages=messages, route_fingerprint=route_fingerprint,
                **({"response_format": response_format} if structured_output else {}),
            )

            async def call(payload: list[dict[str, str]] = messages, output_format: dict[str, Any] = response_format) -> dict[str, Any]:
                return await invoke(payload, output_format)

            response = await extract_once(journal, identity, call, direct_client=direct_client,
                                          direct_messages=messages, direct_max_output_tokens=direct_max_output_tokens,
                                          **({"response_format": response_format} if structured_output else {}))
            source_section = source_section_label(doc.source_text, unit)
            if source_section and len(corpus.documents) > 1:
                source_section = f"{doc.title} (документ {doc_index}): {source_section}"
            if not source_section:
                warnings.append(f"Документ {doc.doc_id}: у фрагмента {unit.start}:{unit.end} нет подтверждённого заголовка раздела")
            if not response["rules"]:
                warnings.append(f"Документ {doc.doc_id}: фрагмент {unit.start}:{unit.end} не дал правил; проверить полноту")
            for raw in response["rules"]:
                quote = raw.get("source_quote", "")
                if not quote:
                    warnings.append(f"Правило {raw['rule_id']}: цитата в целевом фрагменте не подтверждена")
                elif normalize_literal_quote(quote) not in normalize_literal_quote(unit.text):
                    candidates = find_rendered_quote_spans(doc.source_text, quote)
                    if (len(candidates) == 1 and unit.start <= candidates[0][0] < candidates[0][1] <= unit.end
                            and rendered_candidate_preserves_table_boundaries(
                                doc.source_text[candidates[0][0]:candidates[0][1]], quote)):
                        quote_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()
                        quote = doc.source_text[candidates[0][0]:candidates[0][1]]
                        warnings.append(f"Правило {raw['rule_id']}: цитата связана с точным текстом с учетом "
                                        f"форматирования, исходный ответ SHA256={quote_hash}; требуется проверка")
                    else:
                        warnings.append(f"Правило {raw['rule_id']}: цитата в целевом фрагменте не подтверждена")
                if raw.get("doc_id") not in (None, "", doc.doc_id) or raw.get("source_revision") not in (None, "", doc.source_revision):
                    warnings.append(f"Правило {raw['rule_id']}: ответ модели содержит неверную привязку к источнику")
                rules.append(RuleEntity(
                    rule_id=raw["rule_id"], section=source_section or raw.get("section", ""), title=raw.get("title", ""),
                    statement=raw["statement"], conditions=tuple(raw.get("conditions", ())),
                    exceptions=tuple(raw.get("exceptions", ())), actors=tuple(raw.get("actors", ())),
                    timing=raw.get("timing", ""), consequences=raw.get("consequences", ""),
                    source_quote=quote, doc_id=doc.doc_id, source_revision=doc.source_revision,
                    source_family=f"{doc.doc_id}/{family_ids[index]}" if family_ids[index] else "",
                    source_topic=source_table_topic(unit),
                    source_start=unit.start, source_end=unit.end,
                ))
    if len(corpus.documents) > 1:
        warnings.append("Необходимо проверить ссылки между выбранными документами")
    if not rules:
        raise ValueError("v3_partitioned_no_rules")
    source_sha = hashlib.sha256("\n\n".join(source_texts).encode("utf-8")).hexdigest()
    return DocumentRuleModel(document_title=corpus.documents[0].title, document_sha256=source_sha,
                             rules=tuple(rules)), warnings
