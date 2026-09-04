# SEC-RV-001 impact addendum: CMI ingress enforcement v1

Status: Accepted
Owner: root
Approved by: product owner through the 2026-09-04 instruction to start the remediation program

## Trigger

The accepted CMI policy validates decoded data. FastAPI decodes request bodies before
the route function runs, so the route-level serialized-size check alone cannot bound
memory consumed by an oversized or chunked request.

## Additional owned seam

`ScormCommitBodyLimitMiddleware(app, api_prefix, max_body_bytes)` owns only POST bodies
matching `{API_PREFIX}/scorm/attempts/{attempt_id}/commit`.

## Invariants

- Declared and actual body bytes are capped before request decoding.
- Missing `Content-Length` does not disable the actual-byte cap.
- Invalid or conflicting `Content-Length` is rejected without calling the route.
- Non-SCORM routes are unchanged.
- Error responses contain stable codes and never echo the body.
- The existing `CmiCommitPolicy` remains the authority for decoded CMI fields and
  cumulative persisted state.

## Verification

- Oversized declared body: 413, downstream not called.
- Oversized chunked body: 413, downstream not called.
- Invalid declared length: 422, downstream not called.
- Bounded body: replayed unchanged to the route.
- Unrelated route: not constrained by this middleware.

## Release gate

The 128 KiB value is provisional until a read-only inventory of current persisted CMI
and representative customer packages is complete. No production release may use this
addendum as compatibility evidence by itself. Any required widening needs a new impact
addendum and bounded justification.
