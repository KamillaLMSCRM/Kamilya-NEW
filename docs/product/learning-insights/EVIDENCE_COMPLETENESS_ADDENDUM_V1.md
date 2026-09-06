# Latest-attempt completeness

Accepted by root within LEARNING-INSIGHTS-01 implementation authority, 2026-09-06.

Review found that selecting the last available *question* could substitute an older
answer when the actual latest quiz attempt is invalid, lacks this question, or
uses another question definition. This would misstate remediation outcomes.

The first baseline remains unchanged. Select the actual latest completed attempt
per employee/quiz/release inside date_to before projecting questions. If its exact
question definition cannot be verified, retain the first baseline but mark the
latest observation unavailable. Never carry forward an older answer.

QuestionStats adds required latest_respondents and latest_unavailable. Its
latest_incorrect_percent is nullable: null when latest_respondents is zero.
Latest percentages use latest_respondents, not respondents. Improved/regressed
counts include only comparable verified first/latest pairs. UI displays both the
latest denominator and missing-comparison count, never null as 0%.

API/UI owners must update DTOs and synthetic contract tests together. No grading,
release storage, new dependency, role, provider, or production scope changes.
