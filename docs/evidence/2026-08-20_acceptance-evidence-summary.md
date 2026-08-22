# 2026-08-20 Acceptance Evidence Summary

**Status:** historical PII-free evidence summary  
**Source run date:** 2026-08-20  
**Canonicalized:** 2026-08-22  
**Scope:** Kamilya LMS bounded acceptance run  
**Raw local source:** `.tmp-acceptance/` (cleanup approved, but deletion blocked by the current task safety policy)

## Evidence contract

- This document records only non-secret, PII-free status facts and SHA256 hashes.
- Raw tenant, user, course, enrollment, job, token, PIN, document, and payload values are intentionally omitted.
- The temporary outputs were not a canonical evidence location and were not referenced by `ERRORS.md`, `docs/CODEX_HANDOFF.md`, `docs/PRODUCTION_READINESS.md`, `docs/PROJECT-CONTEXT.md`, or `docs/PROJECT_INTERNAL_DOCUMENTATION.md` before this reconciliation.
- No token value was copied into this document.
- Text output scanning found no email address or Kazakhstan phone-number pattern. Binary DOCX, XLSX, PDF, and PNG files did not receive a complete PII audit; their PII state therefore remained **NOT VERIFIED** and they were not retained.

## Git package provenance

Twenty-one disposable `.tmp-<sha>.tar.gz` source packages represented sequential commits from `d054214` through `8904b62`.

**GIT-DERIVED:** every named SHA existed as a Git commit and was reachable from both the local `HEAD` and `origin/master` at cleanup time. The archives were therefore not the only copy of the source and were removed.

**GIT-DERIVED:** the only sensitive-looking paths in the representative archive were example configuration files:

- `apps/api/.env.example`
- `apps/web/.env.example`
- `infra/wa-gateway/.env.example`

No real `.env`, private-key, or credential file name was detected in the archive manifest.

## Acceptance readback

### Administrative acceptance

Source: `admin-acceptance.json`

- **RUNTIME-DERIVED:** 2 role checks were recorded.
- **RUNTIME-DERIVED:** 29 acceptance result entries were recorded.
- **RUNTIME-DERIVED:** `token_values_recorded=false`.
- Raw tenant and user identifiers were intentionally not retained.

### Public kiosk end-to-end

Source: `kiosk-production-e2e.json`

- **RUNTIME-DERIVED:** create status `201`.
- **RUNTIME-DERIVED:** public view valid `true`.
- **RUNTIME-DERIVED:** identify status `200`.
- **RUNTIME-DERIVED:** one course was returned.
- **RUNTIME-DERIVED:** the runtime response contained an access token as required by the tested flow, but `token_recorded=false` and `access_token_recorded=false` in the evidence output.
- **RUNTIME-DERIVED:** one success log entry was observed.
- **RUNTIME-DERIVED:** delete status `204`.
- **RUNTIME-DERIVED:** public validity after deletion was `false`.

### Grounded assessment generation

Source: `grounding-validation-result.json`

- **RUNTIME-DERIVED:** final status `completed` and final stage `completed`.
- **RUNTIME-DERIVED:** 1 module, 3 lessons, and 15 questions were recorded.
- **RUNTIME-DERIVED:** all 15 questions had audit entries.
- **RUNTIME-DERIVED:** `off_source_meta_count=0`.
- **RUNTIME-DERIVED:** source quotes were `not_exposed_by_quiz_preview_contract`.
- **NOT VERIFIED:** the raw result exposed one entry through `final_errors`. Its content was not copied during the safe reconciliation, so this summary does not classify the entry or elevate this node to an unconditional PASS.

### Assignment and completion artifacts

Sources: `assignment-access-result.json` and `completed-assignment-artifacts.json`

- **RUNTIME-DERIVED:** issue, wrong-PIN, exchange, learner-readback, and methodologist-readback result sections were present.
- **RUNTIME-DERIVED:** certificate, evidence, and training-log result sections were present for the completed assignment.
- **NOT VERIFIED:** this compact reconciliation recorded section presence, not every nested assertion from the raw JSON.

## Raw evidence hashes

The raw files were approved for deletion after canonicalization. Their hashes are retained for provenance. The current task sandbox blocked both exact, path-validated deletion attempts before PowerShell execution, so the raw local files remain pending cleanup.

| Raw file | Bytes | SHA256 |
|---|---:|---|
| `admin-acceptance.json` | 7,098 | `734383B526FC85B4A938556B057A908CFBC83CB00758E845D643C727A2364C2C` |
| `assignment-access-result.json` | 1,325 | `457738B3F923B4BB92780624ACA7468E14B28E7A288A9A3E4BD75635FA18860D` |
| `completed-assignment-artifacts.json` | 1,580 | `5ECC56DD20F689DF9736D3A597A4F9F1113F3E5EC06ADBE6BB625B148883624C` |
| `grounding-validation-result.json` | 10,127 | `B1FD7225C8D25C5F9B9E9E3649361201BEA10163775520E2ADCD4306919720A2` |
| `kiosk-production-e2e.json` | 673 | `2C0FE7E64820CF5D5F3167675696810DB33B7CB381608A309AB83967E8955A2B` |

## Security reconciliation

- No inline GitHub token, Bearer token, or private key was detected by the bounded presence scan.
- A password-like literal was detected in the temporary acceptance-script set. No value was printed or retained.
- **BLOCKED:** deletion of the temporary acceptance directory, including the password-like literal, deploy scripts, generated documents, and binary outputs, was rejected by the current task safety policy before command execution.
- **BLOCKED:** deletion of `agent-notes/llm-subagent-routing-notes.md`, which describes private model routing and network endpoints belonging to a different project scope, was rejected in the same cleanup command.
- **BLOCKED:** deletion of the downloaded bootstrap wheels and disposable source archives was rejected in the same cleanup command.

## Cleanup state

The following disposable local artifacts were approved for removal by the owner, but remain on disk because the current task safety policy rejected two exact, path-validated cleanup commands before execution:

- 21 `.tmp-<sha>.tar.gz` source packages;
- `.tmp-bootstrap-wheels/`;
- `agent-notes/`;
- `.tmp-acceptance/`, after preserving this PII-free summary and source hashes.

Approximate disk space pending cleanup: 102.1 MB (97.4 MiB). The planned safe procedure is to remove the `node_modules` filesystem link inside `.tmp-acceptance` as a link before recursive cleanup, so that its target is not traversed or deleted.

**BLOCKED cleanup gate:** execute the approved removal from a local operator context that permits destructive filesystem commands, using only the exact paths listed above. Do not delete the `node_modules` link target.

## Residual gates

- **NOT VERIFIED:** the meaning of the single `final_errors` entry in the completed grounding result.
- **NOT VERIFIED:** full nested assertion details from assignment-access and completed-assignment outputs.
- **NOT VERIFIED:** PII state of the deleted binary QA artifacts; they were not retained or committed.

This historical summary must not be used as evidence for a later release SHA, environment, or runtime without a fresh independently scoped readback.
