# DEV delivery dependency gate correction

Status: Accepted by root within owner-approved DEV delivery,2026-10-21.
Trigger: exact candidate dc363386 CI39554741439 blocks on Pillow12.3.0,
certifi2026.7.22 and follow-redirects1.16.0 advisories. No audit bypass allowed.

Scope extension: API pyproject/Poetry lock/Render requirements and web package/
pnpm lock. Pin Pillow13.0.0 and certifi2026.10.19; constrain the transitive
follow-redirects1.16.1 without changing axios/Next or application interfaces.
These versions are verified in primary upstream release/advisory/PyPI metadata.
Pillow drops Python3.10; Kamilya declares Python^3.12 and CI/runtime use3.12.

Data/auth/provider/model/roles/schema/feature scope unchanged. Production remains
forbidden. Root owns lockfile review: unrelated graph updates are rejected.
Verify lock consistency, fresh blocking dependency audits, PDF/certificate/image
regressions and exact-SHA CI before continuing the same DEV packet. Existing
converter dependencies are separate and not modified. Rollback is old DEV code
and flag OFF; do not weaken gates or add ignored advisories.
