# Owned DEV retention maintenance

Status: Accepted technical correction, 2026-10-17. No production authority.
EPIC_V1 and earlier addenda remain unchanged.

The application role has no DELETE privilege/policy on organization_change_plans.
Only the existing canonical DEV database owner connection can run the explicit
tenant-scoped retention adapter. No new privileged database role, session GUC
maintenance bypass, HTTP endpoint or automatic job is introduced.

Entry point: scripts/ops/staff_structure_dev_retention.py. It validates the supplied
file's non-production APP_ENV allowlist AND pinned canonical Supabase DEV project
fingerprint before connecting, expected0182 schema and exact tenant existence, then invokes
purge_change_plans on the owner connection. Default is dry-run with rollback.
--execute commits at most --batch-size records (1..500, default100). Eligible ready
plans expired more than24h ago and receipts executed more than90days ago only.
Ordering is created_at/id; locked plans are skipped. Other tenants, recent plans,
placements, enrollment content/provenance and durable preservation markers survive.
The marker's nullable plan_id becomes NULL by FK when its receipt expires.

This is an on-demand maintenance path, NOT an enabled retention scheduler. No
actual public DEV purge is authorized by merely installing the script. Operational
execution must name its tenant and approved environment; current integration gate
runs it only on disposable synthetic state in its owned isolated DEV schema.
Before enabling unattended cleanup, wire this same bounded adapter into an owned
administrative scheduler and verify identity/retention/locking again.
