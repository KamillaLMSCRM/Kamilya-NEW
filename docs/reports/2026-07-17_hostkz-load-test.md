# HostKZ database load test

**Date:** 2026-07-17
**Status:** completed on the isolated HostKZ test database
**Production impact:** none; Render and Supabase were not switched or changed

## Decision

The HostKZ configuration with 2 vCPU, 2 GiB RAM and 50 GiB NVMe is sufficient
for the database contour of the first tenant and for a pilot with up to 500
connected users, provided their activity resembles normal LMS usage rather than
500 users continuously sending requests without think time.

At 500 connections and a deliberately conservative rate of 150 database
workflows per second, the test completed without errors. Sampled p95 database
latency was 4.108 ms and p99 was 9.906 ms. Memory, swap and disk were not
bottlenecks.

The first scaling limit is CPU. Under an artificial saturation test the server
reached about 1,386 workflow transactions per second, CPU idle fell to roughly
4-5%, and sampled p95 latency increased to 396.510 ms. More RAM or NVMe alone
will not remove this limit; the next performance upgrade should add vCPU.

This is a database sizing result, not an end-to-end production guarantee. The
API, workers, Redis/Valkey, AI providers and object storage were outside this
test.

## Test contour

| Component | Configuration |
|---|---|
| VPS | HostKZ, Astana, 2 vCPU, 2 GiB RAM, 50 GiB NVMe |
| Database | PostgreSQL 16.14, isolated `kamilya_lms_test` copy |
| Pooler | PgBouncer 1.22, transaction mode |
| Runtime role | `lms_app`, RLS enforced, no `BYPASSRLS` |
| PostgreSQL pool | 10 default + 2 reserve server connections |
| PgBouncer clients | up to 600 client connections, 4096 file descriptors |
| Dataset | current test snapshot, about 24 MiB |
| Generator | `pgbench` on the same VPS |

Running the generator on the database VPS consumes part of the same CPU. The
saturation capacity is therefore conservative, but it does not include network
latency.

## Workload model

Each transaction represented one small learner workflow and started by setting
the transaction-local tenant context used by RLS.

- 80% read workflows: enrollment, course, module, lesson and progress reads;
- 20% write workflows: the application's atomic lesson-progress upsert followed
  by a progress read;
- 1,000 deterministic test slots were built from real relationships in the
  isolated snapshot;
- PgBouncer transaction pooling was used for every test;
- the realistic 500-user profile was rate-limited to 150 workflows per second;
- saturation profiles intentionally removed think time to find the ceiling.

The helper schema and temporary password file were removed after the run. Raw
performance logs remain on the one-week test VPS under
`/home/kamilya/loadtest-results` and contain latency metrics, not row contents.

## Results

Percentiles are calculated from a 10% transaction sample. No test produced a
failed transaction.

| Profile | Duration | Transactions | Throughput | Average | p50 | p95 | p99 | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Saturation, 10 clients | 30 s | 42,422 | 1,415.19/s | 7.064 ms | 6.689 ms | 10.856 ms | 18.294 ms | 0 |
| Saturation, 50 clients | 30 s | 42,049 | 1,404.57/s | 35.571 ms | 34.930 ms | 43.593 ms | 51.588 ms | 0 |
| Saturation, 100 clients | 30 s | 40,219 | 1,350.03/s | 73.971 ms | 73.417 ms | 85.629 ms | 96.161 ms | 0 |
| Realistic, 250 clients, target 100/s | 30 s | 2,807 | 95.59/s | 2.320 ms | 2.005 ms | 4.004 ms | 6.838 ms | 0 |
| Realistic, 500 clients, target 150/s | 60 s | 8,734 | 148.42/s | 2.305 ms | 1.964 ms | 4.108 ms | 9.906 ms | 0 |
| Saturation, 500 clients | 30 s | 40,548 | 1,386.03/s | 358.380 ms | 359.484 ms | 396.510 ms | 417.355 ms | 0 |

The 500-client connection ramp took about 1.16 seconds. PgBouncer multiplexed
those clients over the small PostgreSQL server pool without exhausting database
connections.

## Resource observations

During the realistic 500-client profile:

- CPU was generally about 15-20% busy during the steady section;
- available memory stayed near 1.5 GiB after the run;
- swap usage remained zero;
- observed NVMe utilisation stayed low and write latency remained around 1 ms
  or below in the sampled intervals.

During 500-client saturation:

- CPU reached about 95-96% busy, mostly user and system time;
- the runnable queue peaked above the two available vCPUs;
- disk utilisation remained far below saturation;
- swap activity remained zero.

The result is consistent across the 10, 50, 100 and 500 saturation stages:
throughput plateaus around 1.35-1.41 thousand workflows per second while
latency rises as clients wait for CPU.

## What this proves

- 500 client connections can be accepted safely through PgBouncer.
- The current RLS-aware read/progress workload has substantial headroom at 150
  database workflows per second.
- 2 GiB RAM and the current NVMe are sufficient for the present pilot dataset.
- CPU, not PostgreSQL connections, memory or disk, is the first capacity limit.

## What this does not prove

- 500 browser users can use every application flow at once without API limits.
- Render API latency and connection behaviour against Kazakhstan have been
  measured.
- AI generation, Celery queues, Valkey, email, Telegram, file uploads, SCORM,
  imports and certificate generation have been load-tested.
- A 24 MiB snapshot predicts query plans for a future multi-gigabyte database.
- A 60-second realistic run proves long-term stability, backup interference or
  recovery behaviour.

## Production recommendation

1. Keep Supabase as production during the one-week HostKZ trial.
2. Accept this VPS for a database pilot and first-tenant staging test.
3. Before cutover, connect a staging API to HostKZ through an SSH/VPN/private
   route and run the existing k6 mixed profile at 50, 100, 250 and 500 users.
4. Run a 30-60 minute soak with learner reads, progress, quizzes and admin
   lists; test AI jobs separately because they are asynchronous and provider
   limited.
5. Monitor CPU, PgBouncer queueing, PostgreSQL latency and connection counts.
   Scale vCPU when sustained CPU exceeds 70% or database p95 exceeds the agreed
   application budget.
6. Do not use the VPS as production until off-site backups, restore testing,
   monitoring and a rollback path to Supabase are in place.

For production resilience, 4 GiB RAM is still preferable even though this test
did not exhaust 2 GiB. It provides operational margin for maintenance, larger
caches and temporary query spikes. For raw throughput, however, additional
vCPU has higher priority than additional RAM.

## Reproduction

The SQL workload and runner are stored in `tests/load/pgbench`. They require an
isolated database populated with test data. Never run the write profile against
a production tenant.
