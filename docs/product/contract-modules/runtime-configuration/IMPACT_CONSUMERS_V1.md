# Additional verified consumers V1

Accepted root2026-10-16, same owner-authorized DEV scope; supplements EPIC_V1 impact matrix before edits.

| Module | Impact | Permitted change | Preserved/test |
|---|---|---|---|
| Workbench document_answers | Consumer | separate content-answer total/provider/token knobs | same source retrieval/citation completeness, lease120s, evidence_low profile, cancellation/refunds; document-answer regressions |
| Editor assistant provider resolver | Consumer | temperature/token knobs | tenant UUID required, existing current schema/max4096, no new calls; tenant-routing tests |
| AI writer retrieval | Consumer | existing n_results/top_n/threshold defaults | tenant/doc/provenance enforced; explicit caller values preserved, no higher caps than prior defaults; source retrieval tests |
| Model-routing admin response | Consumer | show effective managed model names from runtime snapshot | unchanged route order/readiness/endpoint/key protection; routing contract tests |

Operation maximum remains90s in this package (client has no shorter Axios deadline; operator probe95s is acceptance-only). DeepSeek knob may be adjusted5..60s provided all assignment attempts plus5s fit within90s; related knobs change in one atomic bundle. This corrects the initial overly tight30s ceiling without changing the owner-approved default30s. No provider availability/capacity guarantee.

Model-order revisions remain independent from settings revisions per IMPACT_REVIEW_V1. Admin response reports effective names, avoiding stale env-only UI. No combined policy save.
