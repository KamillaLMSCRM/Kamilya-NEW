# ADR-0007: AI pipeline — Qwen primary, DeepSeek/Voyage failover

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context:** AGENTS.md §LLM failover chain, audit §6

## Decision

We run a two-tier LLM/embeddings stack with automatic failover:

**LLM (text generation):**
1. **Qwen self-hosted** (primary) — `https://qwen.kml.kz/v1`,
   model `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit`. Free at the network
   level (DGX machine, no per-token cost). Higher latency on first
   token because of network tunneling through the office VPN, but
   free.
2. **DeepSeek v4-flash** (fallback) — `https://api.deepseek.com/v1`,
   model `deepseek-v4-flash`. $0.14/$0.28 per 1M tokens.
   Activated only when Qwen fails (timeout, 5xx, circuit-breaker
   opens). Used as a reliability backstop, not as primary cost
   optimization.

**Embeddings:**
1. **Qwen self-hosted** (`Qwen3-Embedding-8B`) — primary, free.
2. **Voyage voyage-4-lite** — fallback. $0.02/M tokens with 200M
   free tokens per account.

Provider keys resolution priority (per provider):
1. Environment variable (`DEEPSEEK_API_KEY`, `VOYAGE_API_KEY`)
2. Active global key in `provider_keys` table (superadmin-managed)
3. Provider skipped from the chain

## Why not single-cloud from the start

Qwen on the local DGX was the cheapest option (zero marginal cost) and
keeps document content on infrastructure we control — important for
Kazakh legal-entity customers who have data-residency concerns. The
failover to DeepSeek/Voyage exists purely for reliability, not for cost
arbitrage.

## Operational constraints

- **ResilientLLMClient / ResilientEmbeddingsClient** in
  `apps/api/app/modules/ai/llm_client.py` orchestrate the chain.
- **Embeddings endpoint must be `/embeddings`** — the unified
  `_BaseProviderClient._request()` was previously hard-coded to
  `/chat/completions` for both LLM and embeddings (lesson 1 from
  AGENTS.md). EmbeddingsClient now overrides to `/embeddings`.
- **NaN-filtering** — embeddings are checked for None/NaN/inf before
  pgvector insert (lesson 4).
- **`embedding_status` reflects actual embeddings written**, not chunks
  produced (lesson 2).
- **`chunk_id` = md5(doc_id + text)**, not just md5(text) (lesson 5c) —
  prevents cross-document collision on re-upload.

## Alternatives considered

- **OpenAI / Anthropic as primary.** Rejected — per-token cost at our
  expected volume (10K docs × 5 embeddings × 1000 tokens each) would
  exceed DeepSeek fallback cost by 5-10x and adds data-residency
  concerns.
- **OpenRouter aggregator.** Could add Claude Haiku as a 3rd tier for
  the reviewer role. Deferred — current reviewers run on Qwen fine.
- **Per-tenant provider keys.** Currently global only (provider_keys
  rows have `tenant_id=NULL`). Architecture supports per-tenant but UI
  not built — deferred until enterprise tier demands it.

## Open items

- **Per-tenant LLM budget** (`tenant_settings.monthly_llm_budget_usd`)
  not yet implemented. Needs metrification first to know what a
  reasonable cap is.
- **Quality-tier reviewer model** (e.g. DeepSeek v4-pro or Claude
  Sonnet) — currently Qwen reviews its own output. Acceptable for v1,
  revisit after first month of production quality metrics.