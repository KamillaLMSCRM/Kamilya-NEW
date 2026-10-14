# Editor chat history V1.2 — quoted-instruction admission

Status: Accepted by Root 2026-10-14 before repair.
Amends V1/V1.1; bounds, owners and release exclusions remain unchanged.
Independent finding ASSISTANT-HISTORY-POISON-001 reproduced by an actual RED
API test: a safe reply quoting a denied instruction remains visible and is not
an output-policy refusal, but replay screening would poison subsequent questions.

Normal visible reply, optional proposal/title and audience advice receive
history_eligible=False when their text matches the existing request-refusal
policy. This does not suppress an otherwise-safe visible reply or change
audience decisions; it only excludes this completed exchange from future model
context. Reply safety, target filtering and existing redaction remain unchanged.
Root owns these exact /chat admission fields and regression tests. Re-review
the finding after repair; preserve the original failed independent review.
