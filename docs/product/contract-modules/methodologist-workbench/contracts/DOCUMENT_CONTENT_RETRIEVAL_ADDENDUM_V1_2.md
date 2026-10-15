# Document content retrieval addendum V1.2

Accepted by Root under the same owner's DOCUMENT57 request, 2026-10-15.
Extends V1/V1.1 without rewriting consumed contracts. Second live DEV candidate
passed26/28 cases, with one partial and one failure. The remaining retention
omission was reproduced without a model: eight short chunks consumed only5797
characters but excluded the requested rule at verified prefix chunk5.

## Bounded implementation

Keep lexical search, verified prefix indices0–6, per-source queues and depth-wise
balancing unchanged. Allocate the existing sixteen immutable1500-character
windows directly instead of stopping after eight arbitrary-size chunks. Thus
up to sixteen short chunks may fit, but evidence remains at most24000characters,
sixteen handles and eight public citations. A3000-character chunk still takes two
windows. Stop before a seventeenth handle. No added retrieval query, embedding,
model call, maximum input-character budget, output-token budget, retry or deadline.
Actual text sent may increase within the existing ceiling; no cost-savings claim.

Preserve deduplication, exact source/revision/hash validation, tenant isolation,
redaction and terminal witnesses. No public shape or schema change. The bounded
prefix is still not exhaustive retrieval for long documents.

Classify the answer against the requested facts. A contradiction on an unrelated
topic must not replace the requested comparison or change its status. For priority
follow-ups, distinguish unresolved contradictory values from verified validity:
no source precedence does not prove that both rules are currently in force.

## Required proof

RED/GREEN tests through retrieve must expose a later relevant short chunk after
lexical-heavy candidates while preserving sixteen windows/24000characters and
the existing long-chunk tail test. Actual DEV read-only replay must contain RU30
days as well as KK60days and the3/5day conflict facts. Preserve all earlier failed
answers and independent semantic reviews. Repeat the consumed regressions and
the pre-frozen, still unseen warehouse holdout, then isolated DEV gate, exact CI,
ordinary-role browser/model acceptance and protected production verification.
Voice untouched and reserveOFF. Schema0181/native frontend56 remain compatible.
