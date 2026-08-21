# Kazakhstan Compliance Course Catalog

Status: product and legal blueprint
Reviewed at: 2026-08-21
Jurisdiction: Republic of Kazakhstan

## 1. Purpose and boundary

This catalog defines reusable compliance-training templates for Kamilya LMS. It
specifies delivery mode, target audience, applicability questions, source
controls, tenant configuration, and versioning. It is a product specification,
not legal advice and not a determination that a course is mandatory for every
employer, employee, industry, or tenant.

The catalog must not convert a general legal duty into a universal assignment.
Applicability depends on the tenant's activity, hazards, information systems,
personal-data processing, regulated status, job functions, local acts, and
current official requirements. A tenant's responsible legal, HSE, information
security, or compliance owner must approve the applicability decision and any
required provider or certification route before publication or assignment.

Kamilya LMS may provide awareness, induction, knowledge checks, records, and
completion evidence. It must not represent an LMS completion record as a state
license, permit, professional qualification, attestation, or external
certificate unless that outcome is actually issued by an authorized provider
under the applicable rules.

## 2. Delivery classes

### `lms_only`

Training, awareness, induction, or internal instruction delivered and recorded
entirely in Kamilya LMS. The tenant owns the instructional approval and may
issue an internal completion record. This class does not imply that LMS-only
completion satisfies a separate practical training, examination, attestation,
authorization, or provider requirement.

### `blended`

Kamilya LMS supplies the digital theory, induction, preparation, or evidence
capture, and a tenant or approved external party supplies a required live,
practical, supervised, oral, workplace, or examination component. The record
must show each component separately and must not mark the overall requirement
complete until the configured external or practical evidence is accepted.

### `external_certified`

The legally or contractually relevant qualification, certificate, attestation,
or authorization is issued by an authorized external provider, competent body,
or other party specified by the applicable requirement. Kamilya LMS may manage
pre-learning, assignments, expiry reminders, provider evidence, and audit
records, but it is not the issuing authority. Provider identity, authorization
scope, certificate number, issue date, expiry date, and evidence reference are
required where applicable.

## 3. Catalog waves

Wave labels are delivery priorities, not legal priority or a claim of universal
mandatory status.

### Wave 1: initial reusable templates

| Template | Default class | Intended scope | Applicability guard |
| --- | --- | --- | --- |
| Universal information security, personal data, and cyber hygiene | `lms_only` | Baseline awareness for personnel who use organizational systems or handle organizational information | Assign only after the tenant confirms the relevant systems, data, users, and internal policy scope; do not label it a universal statutory course |
| Finance information-security overlay | `lms_only` or `blended` | Finance, accounting, payment, treasury, and other roles with elevated financial-system or financial-data exposure | Requires tenant confirmation of financial operations, systems, role population, customer/payment data, and any sector or group policy; external assessment is separate if required |
| Occupational safety induction | `blended` by default | New, transferred, temporary, contractor, or otherwise in-scope personnel before applicable work begins | Requires tenant HSE owner to identify workplace, role, hazard, induction stage, practical briefing, and sign-off rules; LMS record alone is not proof of every required workplace action |
| Fire-safety instruction | `blended` by default | Personnel and roles covered by the tenant's fire-safety arrangements | Requires site, shift, role, evacuation, equipment, local instruction, and practical/external component review; do not assign as a universal course without an applicability decision |

Wave 1 templates must ship with configurable audience rules and an explicit
decision state: `applicable`, `not_applicable`, `needs_review`, or
`external_required`.

### Wave 2: candidates subject to gates

The following are candidates only. No template may be published as a compliant
course until its gate is closed for the target tenant and activity:

| Candidate | Required gate before publication or assignment |
| --- | --- |
| PTM (fire-technical minimum) | Confirm the exact activity, premises, personnel category, required instruction/qualification, and an authorized provider or competent internal route |
| Industrial safety | Confirm regulated hazardous facilities, equipment, roles, training/attestation duties, and competent provider or authority requirements |
| Electrical safety | Confirm electrical installations, assigned duties, access level, group/qualification requirements, practical work, and authorized attestation route |
| First aid | Confirm workplace risk, designated responders, practical training, trainer/provider competence, renewal, and evidence requirements |
| Sanitary minimum | Confirm sector, sanitary role, personnel category, examination or certification requirement, and authorized provider route |
| AML/CFT | Confirm reporting-entity or other regulated status, covered activities, role-based duties, internal controls, and current sector requirements |
| Civil defense | Confirm facility/category, civil-defense organization, assigned formations or roles, exercises, and competent authority requirements |
| Road safety | Confirm vehicle operation, driver/dispatcher roles, route and fleet profile, pre-trip/line-control duties, and required briefing or examination |
| Environmental compliance | Confirm emissions, waste, water, hazardous substances, permits, responsible roles, monitoring duties, and external competence requirements |

The gate owner must record the decision, rationale, tenant scope, source set,
provider/authority evidence, and next review date. A candidate may remain in
`needs_review` without being assignable.

## 4. Applicability questionnaire

The tenant's designated owner must answer and retain evidence for the following
questions. Answers must be versioned; changing a material answer triggers a new
applicability review.

1. What legal entity, branches, sites, and activities are in scope?
2. Which industry, regulated, licensed, hazardous, public-facing, or
   financial activities are performed?
3. Which roles are employees, contractors, visitors, drivers, responders,
   supervisors, managers, operators, or designated responsible persons?
4. Which workplaces, shifts, equipment, vehicles, installations, substances,
   premises, and hazards exist?
5. Does the tenant collect, access, store, transmit, or otherwise process
   personal data or restricted business information? Which systems and roles
   are involved?
6. Does the tenant operate information systems, payment/finance systems,
   critical services, or systems subject to group or sector controls?
7. Does the tenant have fire-safety, occupational-safety, civil-defense,
   environmental, sanitary, AML/CFT, or road-safety responsibilities that
   require role-specific instruction, practical work, examination, attestation,
   or a certificate?
8. Which internal orders, policies, risk assessments, permits, registers,
   contracts, collective arrangements, or site instructions affect training?
9. Is an authorized external provider, competent person, medical/practical
   trainer, examination body, or state-recognized attestation required?
10. What language, accessibility, shift, site, delivery, retake, expiry, and
    evidence constraints apply?
11. Who approved the decision, on what date, against which official sources,
    and when must it be reviewed?

The questionnaire is a decision aid. It does not replace legal review or permit
an administrator to self-certify an external qualification.

## 5. Required template metadata

Every template must contain the following metadata before it can be activated:

- stable `template_key`, human title, short purpose, language, and owner;
- wave, delivery class, status, and explicit legal/advisory boundary;
- intended audience and exclusion criteria;
- hazards, systems, data types, activities, sites, and role predicates;
- applicability questions and required evidence;
- learning objectives, modules, assessment rules, pass threshold, attempts,
  remediation, estimated duration, and accessibility notes;
- practical, live, examination, attestation, provider, or certificate
  dependencies, if any;
- completion event semantics and evidence retained by Kamilya LMS;
- validity/expiry policy, refresher trigger, assignment timing, and grace rules;
- source records: official title, URL, provision/topic reviewed, source type,
  reviewer, `reviewed_at`, and next review date;
- change impact, supersedes/superseded-by links, and approval status;
- provider gate status and named gate owner for `blended` or
  `external_certified` templates.

## 6. Required tenant fields

Tenant instantiation must capture, at minimum:

- tenant identity, legal entity, branches/sites, jurisdiction, and responsible
  approvers;
- business activities, industry/regulated status, licenses or permits relevant
  to the template, and applicable internal policy identifiers;
- personnel groups, job roles, contractors, shifts, locations, and audience
  membership source;
- systems and information categories, including personal-data and finance/
  payment-system exposure where relevant;
- workplaces, equipment, vehicles, installations, substances, hazards, and
  emergency/response roles;
- questionnaire answers, evidence references, applicability decision, rationale,
  decision owner, decision date, and next review date;
- selected template version, tenant configuration version, locale, delivery
  class, provider/competent-person details, and external evidence requirements;
- assignment, completion, practical/external component, certificate, expiry,
  renewal, remediation, and audit-retention settings;
- tenant approval status and the last legal/HSE/security/compliance review.

## 7. Immutable instantiation and versioning

An activated tenant course is an immutable instantiation of one immutable
template version plus one tenant configuration version. It stores the exact
content hash, source set, applicability decision, audience rule, delivery
class, assessment configuration, approver, and activation time used for that
assignment.

Template edits never mutate an activated version or rewrite historical
completion evidence. A material change creates a new template version and
requires impact review, approval, and a new tenant instantiation. A tenant may
choose whether to migrate open assignments only when the migration policy
allows it; completed records remain attached to the version completed.

Source withdrawal, legal change, expired provider authorization, or a changed
applicability answer can suspend future assignment and require re-review. The
system must preserve the prior record, reason, actor, timestamps, and successor
version. Deleting a historical version or silently changing its source set is
not permitted.

## 8. Legal-source review workflow

1. Identify the tenant activity and training question; record the applicable
   template and jurisdiction.
2. Retrieve the current text from an official primary source only. Record the
   exact URL, title, relevant provision/topic, retrieval/review date, and
   reviewer.
3. Separate observed legal text from product interpretation. Mark each outcome
   as `mandatory_scope_confirmed`, `role_or_activity_dependent`,
   `provider_or_attestation_dependent`, `internal_policy_only`, or
   `not_established`.
4. Have the designated legal/HSE/security/compliance owner approve the
   applicability decision and provider gate.
5. Publish only the approved template/version and retain the source snapshot or
   evidence reference permitted by the tenant's retention policy.
6. Re-review on a legal change, source update, provider change, material tenant
   change, incident, or scheduled review date. A stale review must not be
   presented as current compliance evidence.

`reviewed_at` is mandatory for every source record and must be visible in the
catalog and tenant audit trail. A date alone is not proof that a requirement is
universal; the reviewed provision and applicability reasoning are also required.

## 9. Official primary sources

Only the following official primary links are approved for the initial
blueprint source set. They are review inputs, not blanket conclusions:

- [Official source V1500012665](https://adilet.zan.kz/rus/docs/V1500012665)
- [Official source V1400009510](https://adilet.zan.kz/rus/docs/V1400009510)
- [Official source V2100023461](https://adilet.zan.kz/rus/docs/V2100023461)
- [Official source V2000021654](https://adilet.zan.kz/rus/docs/V2000021654)
- [Official source V2000021814](https://adilet.zan.kz/rus/docs/V2000021814)
- [Official source V2000021426](https://adilet.zan.kz/rus/docs/V2000021426)
- [Law Z1300000094](https://adilet.zan.kz/rus/docs/Z1300000094)
- [Law Z1400000188](https://adilet.zan.kz/rus/docs/Z1400000188)
- [Code K2100000400](https://adilet.zan.kz/rus/docs/K2100000400)

The catalog must not add secondary summaries, vendor claims, search snippets,
or undated copied text as legal authority. If the official source set does not
establish a requirement for the tenant's facts, the product outcome is
`not_established` or `needs_review`, not a universal assignment.
