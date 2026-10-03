# Native CT137 frontend deployment

Owner-approved and runtime-verified 2026-09-10. This is the ordinary frontend
path; Vercel and Proxmox guest-console login are not release prerequisites.
Infrastructure bootstrap or changing the privilege boundary still needs owner approval.

## Fixed boundaries

- Target: CT137 `webkml`, currently pve3, WireGuard `10.77.77.3`.
- Workstation -> canonical proxy SSH -> pinned CT137 restricted key,
  `kamilya-admin`. Proxy is transport only: no artifact files or builds there.
- Credentials: workspace `C:\Kamilya New\.env`, existing `PROXY_VPS_*` names;
  local known_hosts and proxy `/root/.ssh/known_hosts.ct137` are mandatory.
  Never print credentials, change host-key validation, or use another account.
- `/usr/local/sbin/kamilya-web-deploy` is root-owned0750. Exact doas permission
  permits this command only; no general root shell/install permission is granted.
- `/opt/kamilya-web/releases` is root-owned0755. Only `.next/cache` in new
  releases is writable by `kamilya-web`. Existing rollback release is preserved.
- Native OpenRC `kamilya-web`, Next.js on localhost3000. The independent landing
  service/config and backend/database are outside this helper's write scope.
- No application build or package install on CT137. Build off-host using
  `.github/workflows/build-native-frontend.yml` for the exact accepted source SHA.

## Release procedure

1. Root prepares a digest-bound JSON release packet for exactly one frontend
   SHA. It names exact successful CI and native-build run IDs, the read-back
   current release, one verified rollback release, owner approval and the fixed
   technical smoke scope. `scripts/ops/ct137_native_release.py` is the only
   routine release-level entrypoint; do not manually compose its stage/deploy
   subcommands.
2. With the canonical agent-tools Python (Paramiko already installed), run the
   fail-closed preflight and preserve its evidence:

   Before dispatch, verify the peeled local `refs/tags/v<version>^{}` and remote
   published release tag both equal the exact packet SHA. `gh release create
   --target` does not materialize the local tag. If absent, fetch only that exact
   tag through `with_project_github_token.py` and the canonical project-account
   credential helper; stop on a mismatched existing tag, never force it. This
   prevents an avoidable large-artifact download before a local-source gate fails.

   ```powershell
   $toolPython = 'C:/Users/user/.codex/tool-envs/kamilya-agent-tools/Scripts/python.exe'
   & $toolPython scripts/ops/ct137_native_release.py preflight `
     --packet <absolute-release-packet.json> `
     --packet-sha256 <packet-sha256> `
     --evidence .release-evidence/<release-id>/preflight.json
   ```

   Unless `--artifact-dir` is supplied, the controller downloads the exact
   SHA-scoped GitHub Actions artifact itself. It verifies source/tag/version,
   exact CI identity, bundle digest and archive layout, CT137 status, immutable
   release inventory, rollback presence, privilege boundary and conservative
   free-space budget before staging anything.
3. After reviewing `READY` evidence and confirming the same authorization is
   still current, run the same packet through `execute`:

   ```powershell
   & $toolPython scripts/ops/ct137_native_release.py execute `
     --packet <absolute-release-packet.json> `
     --packet-sha256 <packet-sha256> `
     --evidence .release-evidence/<release-id>/technical-readback.json
   ```

   Execute repeats every preflight gate, creates only the required temporary
   SHA-scoped manifest copy, stages the exact archive/manifest pair, deploys once,
   then reads back CT137 status and the public frontend/API identity. A stopped
   preflight or execute is a block, never permission to fall back to manual
   staging. `ct137_native_deploy.py` remains a lower-level maintenance and
   recovery tool.
4. Helper verifies baseline, snapshot/digest, sidecar, paths/links, archive size,
   expanded bytes and disk reserve; extracts without executing package code;
   atomically switches and waits for application routes. Failure after switch
   triggers restoration of symlink, marker and Nginx plus old-app startup checks.
5. Technical readback deliberately returns
   `product_acceptance=SEPARATE_TEST_RUNNER_REQUIRED`. Test Runner then performs
   the changed authenticated user journey. Release Runner does not absorb or
   silently skip that responsibility; HTTP 200 and an exact marker are not
   product acceptance.
6. Preserve release/rollback evidence and current operational state. Do not call
   the release accepted if the separately owned browser/API acceptance is still
   incomplete.

## Capacity, cleanup and recovery

### Explicit no-console cleanup

#### Standing owner authorization for routine obsolete frontend cleanup

Owner confirmed on 2026-10-02 that repeated, identical frontend cleanup requests
must be handled by this standing rule, without a new approval each time. This
authorization applies only to obsolete LMS frontend release directories and their
exact matching user-owned staging archive/manifest pairs on CT137. It is not an
automatic scheduled deletion or permission to expand maintenance scope.

Root may select one obsolete release at a time only when all checks below pass.
For future actions, bind this authorization to a frozen, digest-verified packet for
one owner-authorized ordinary CT137 frontend release, its freshly inspected native
artifact and its computed `required_capacity_bytes(artifact)` budget (successful
controller evidence field `artifact.required_capacity_bytes`). Require live free bytes below
that exact budget. Only a previously successful frontend release with product
version strictly older than the actual rollback version is eligible; select the
oldest eligible version from the live release inventory. A failed candidate,
staging-only artifact, unknown/unversioned release or arbitrary historical pair is
not eligible. The exact24 action recorded below has separate explicit approval.

Inventory provides SHAs, not version/success metadata. For each unprotected
candidate and the actual rollback, inspect its preserved original native artifact
directory with the existing read-only `inspect_native_artifact(directory, full_sha)`
function. The directory must retain the SHA-scoped archive/manifest,
`bundle.sha256`, and any version-required build-config. A canonical local invocation
(no host action) is:

```powershell
py -3 -c "import json,sys; from pathlib import Path; from scripts.ops.ct137_native_release import inspect_native_artifact; a=inspect_native_artifact(Path(sys.argv[1]),sys.argv[2]); print(json.dumps({'release_sha':a.release_sha,'product_version':a.product_version,'archive_sha256':a.archive_sha256,'manifest_sha256':a.manifest_sha256}))" <original-artifact-directory> <full-sha>
```

Compare the validated versions as three integer components, never strings. Bind
prior success to an existing independently accepted historical technical receipt
with `status:RELEASE_OK` and this exact `release_sha`; retain its path and digest.
Inventory presence or a manifest alone does not establish previous success. If
those original files or the accepted receipt are unavailable, classify that SHA
as unknown/protected, not eligible. The cleanup receipt must list every considered
SHA/version/eligibility result plus the successful historical receipt references,
so the oldest eligible choice and rollback-version predicate are independently
reviewable. This uses off-host evidence, not a new privileged remote query.

1. Read back the live current release and its actual previous successful release
   used for rollback; verify both are retained and usable. Never select either,
   a release named as rollback in an active packet, or another explicitly retained
   recovery release. Preserve additional recovery releases
   `359d7cda1fba310a4e2e890fbfc48fef89a3f357` and
   `299481ec1518729bcec199e8aaa2fdfe5c74c1e3` until separately authorized otherwise.
2. An accepted release has successfully switched and its independent technical
   readback passes. Cleanup must not evade a failed release/product gate. If an
   older packet still names the candidate as rollback, explicitly supersede that
   retention disposition before selection; do not silently reinterpret it.
3. Verify an off-host recovery archive and SHA-scoped manifest for the exact
   selected SHA: both SHA256 digests, manifest/archive identity, safe archive
   structure and expanded size. Keep that recoverable pair after server deletion.
4. Obtain a fresh `cleanup-plan` for those exact obsolete/current/rollback SHAs.
   Require the canonical digest-bound helper envelope and tree fingerprint checks;
   do not reconstruct a SHA from a short prefix or stale summary.
5. Delete only the selected obsolete release through `ct137_native_deploy.py
   --cleanup`. With `--prune-staged-copy`, remove its exact staging pair only after
   both remote hashes match the verified recovery pair. Never use broad prune,
   wildcard deletion, direct recursive shell deletion, or whole-directory cleanup.
6. Independently run canonical `ct137_native_deploy.py --status` and `--inventory`
   after cleanup, then read `https://app.kml.kz/healthz` and
   `https://api.kml.kz/health`. Status must show current/marker equal the expected
   current SHA and `kamilya_web_running:true`; public web must return that SHA,
   and API identity must match the pre-cleanup readback. Inventory must contain
   current, rollback and both explicitly preserved extra releases, omit the exact
   selected release and its staging pair (when pruning), and show increased free
   space. Preserve a sanitized receipt with `obsolete_sha`, `current_sha`,
   `rollback_sha`, `preserved_release_shas`, `removed_staging_names`, both recovery
   digests, envelope/tree digests, `free_kib_before`, `free_kib_after`, status/public
   identity results and the authorizing packet ID/digest. A helper success alone
   does not satisfy these separate readback gates. Briefly report recoverability.

For future actions, apply this rule only until the exact packet's required capacity
is restored; never delete another release after that condition passes. If one
cleanup is insufficient, repeat the entire selection/recovery/plan/readback sequence
for the next eligible oldest release under the same packet. Stop and request a new decision
on any identity/hash/plan/readback mismatch, unavailable recovery, unknown rollback,
unexpected partial failure, or need to affect a protected release. No Proxmox,
bootstrap/helper replacement, privilege expansion, API images/containers, volumes,
database, tenants, landing, DNS, credentials, provider tiers or billing are included.

The exact exception approved on 2026-10-02 permits removal of frontend0.11.24
`1e10d9acda443f57fd2714011e1398d5e2e06e1f` after successful compatibility0.11.27
`30693e45e1338772bf09577461e3f7615d38a73b`, preserving actual rollback0.11.25
`3d1276443ad8735a5c0bf3dd029be5768c46ca6a`. This supersedes the older A27 packet's
retention of24 for this maintenance action only; the historical packet is unchanged.

The maintenance extension adds read-only `cleanup-plan <obsolete> <current>
<rollback>` and one destructive `cleanup <envelope-sha256>` command. The
workstation wrapper independently hashes an off-host recovery archive and its
SHA-scoped manifest, obtains the live cleanup plan, creates the exact
digest-bound envelope, stages it as `cleanup-envelope-<sha256>.json`, and invokes
the helper. The envelope is accepted only when its filename digest, exact fields,
current/rollback identities, tree fingerprint, and the root-owned recovery record
created when that exact release was deployed all match the live state.

Only an explicitly named obsolete SHA may be selected. The helper holds the
deployment lock, reads the staged envelope through a no-follow descriptor with
validated owner/mode/size, rechecks active pointers/configuration/processes,
mount and path boundaries, and deletes only that exact release directory using
fd-relative symlink-safe removal. It preserves the current and verified rollback
release. Before deletion the helper requires at least 512 MiB free and writes a
root-owned `STARTED` receipt. A successful operation replaces it with `CLEANED`;
an unexpected deletion or post-check failure leaves a durable failure status.
Validation failures stop before deletion.

The privileged helper never deletes files from the deploy user's staging folder.
After a successful root cleanup, the wrapper rechecks the exact envelope and,
when requested, the matching staged archive and manifest hashes, then removes
those user-owned duplicates without root privileges.

Example from the workstation (recovery inputs remain off CT137):

```powershell
& $toolPython scripts/ops/ct137_native_deploy.py `
  --cleanup <obsolete-sha> <current-sha> <rollback-sha> `
  --recovery-archive <off-host-archive.tar.gz> `
  --recovery-manifest <frontend-native-<sha>.manifest.json> `
  --prune-staged-copy
```

`--prune-staged-copy` is optional. It removes the matching staged obsolete pair
only after both remote hashes match the independently verified off-host pair.
The wrapper emits only sanitized SHA/status evidence. It never builds, installs
dependencies, starts containers, or requires a Proxmox guest-console login.

The transport stages only digest-qualified maintenance files and the envelope;
verify their hashes before root execution. `--verify-boundary` requires the
explicit `--expected-rollback-sha`.

The helper retains current, old and failed releases. It does not silently delete
them. Disk reserve is512MiB in addition to exact required snapshot/extracted
bytes; archive512MiB, expanded regular content2GiB, maximum100000entries.
On a capacity stop, inventory exact paths and apply the standing authorization
above only when all its conditions hold; otherwise obtain exact bounded approval.
Preserve current and a verified rollback; never clear releases/incoming wholesale.
On unexpected failure, inspect status before retrying. For a deployedSHA, continue
acceptance rather than redeploying. Root console is for exceptional bootstrap or
recovery, not an ordinary release dependency.

## Verified installation and first release

- Helper SHA256: `a6379cefe5e558fd9537f4144555d8776804c66b15823957402e01814d23291a`.
- Python3.14.7 installed from the Alpine registry for this helper. Actual existing
  application runtime Node24.18.1; CI artifact used Node20.20.2/musl. Application
  routes and authenticated settings flow passed on the existing host runtime;
  matching the build Node major to runtime remains a separate build alignment item.
- Windows tests15passed/1Unix-onlyskipped; native unprivileged CT137 tests16passed.
  Rollback test verifies state restoration on disposable filesystem fixtures,
  not a deliberate production rollback drill.
- Released `3c0519310d2c435de740eb5aad098b07bf012b1f` (0.4.1), previous
  `e463527cd8f5e67e987c44d8d769f337714bd25f` retained.
- Native CI34454506724; archiveSHA256
  `43b0cd1d311cdeaa77e566ffbacfe4408d7b10ab085651962c02a597f07fbc14`.
  155423605compressed bytes,541686203expanded bytes,17001members.
- Independent SSH status and publichealth exactSHA PASS; general `doas id`
  denied while helper status succeeds. Free space afterrelease2036860KiB.
- Synthetic administrator UI: generation and embedding settings each saved disabled,
  re-entered and read back; keys absent from saved inputs. Both dummy connections
  removed through guarded API cleanup, absence verified. Browser automation stalled
  on its native confirm dialog, so successful UI deletion is NOT claimed.

The original large Excel course generation remains a separate unresolved
acceptance issue; this infrastructure success does not imply that it passes.
