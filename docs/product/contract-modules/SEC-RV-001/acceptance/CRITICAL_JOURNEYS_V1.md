# SEC-RV-001 critical journeys V1

## CJ-01 — valid SCORM 1.2 import

An authorized methodologist imports a bounded package. Intake returns typed metadata;
the existing route creates one course and package and stores one ZIP. Launch remains on
the isolated SCORM origin.

## CJ-02 — adversarial package rejection

DTD/entity XML, malformed XML, encrypted/symlink/unsafe/duplicate/ambiguous or
over-budget ZIP input returns the contracted 400/413 before course, package or storage
write.

## CJ-03 — bounded progress and completion

An active scoped attempt accepts canonical flat SCORM 1.2 progress, merges it within the
cumulative budget, and preserves existing completion/certificate behavior.

## CJ-04 — atomic CMI rejection

Unknown, nested, non-string or over-budget CMI returns 413/422. The attempt JSON and
projected fields are unchanged and no certificate/completion side effect occurs.

## Release evidence

Focused/interface tests are necessary but insufficient. Before release, run existing
SCORM integration on disposable PostgreSQL and the risk-based suite. Before production
sign-off, read back exact API/frontend/worker/DB identity and execute approved benign
and synthetic malicious browser journeys without retaining tokens or CMI content.
