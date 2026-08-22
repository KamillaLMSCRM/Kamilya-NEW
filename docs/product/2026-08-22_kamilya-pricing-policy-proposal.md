# Kamilya LMS Pricing Policy Proposal

**Status:** DRAFT / DISCUSSION ONLY  
**Created:** 2026-08-22  
**Owner:** Kamilya LMS product owner  
**Scope:** Kazakhstan B2B LMS platform, content licensing, onboarding, and related services  
**Commercial status:** This document is not an approved price list, public offer, quotation, or binding commercial commitment.

## 1. Purpose

This document preserves the 2026-08-22 market research and the initial pricing hypothesis for later discussion. Prices must not be published, quoted to a customer, or incorporated into a contract until the product owner approves the relevant version.

## 2. Current Kamilya commercial position

The current landing flow contains:

- a free 14-day self-service trial;
- a demonstration using an agreed subset of customer documents;
- a working launch with an individual calculation;
- B2B contracting rather than a public paid online subscription.

Canonical landing implementation at the time of research:

- `kamilya-landing/messages/ru.json`, `pricing` section;
- `kamilya-landing/components/Pricing.tsx`.

The current landing does not provide a public monetary starting point. This reduces price transparency and makes it difficult for a prospective customer to understand the expected budget range.

## 3. Evidence labels

- **PROVIDER-CONFIRMED:** price published by the vendor on its official website at research time.
- **OWNER-CONFIRMED:** product status or commercial boundary explicitly confirmed by the Kamilya owner.
- **INFERRED:** Kamilya recommendation derived from market evidence and current product positioning.
- **NOT VERIFIED:** requires cost, legal, accounting, or commercial validation before approval.

## 4. Market benchmark

Prices are kept in vendor currencies because direct conversion without contract currency, tax, and exchange-rate rules would be misleading.

| Provider | Pricing model | Public benchmark at research time | Evidence |
|---|---|---:|---|
| TalentLMS | User capacity / flexible active users | USD 119/month for 1-40 users on Core with annual billing | PROVIDER-CONFIRMED |
| 360Learning | Per user | USD 8/user/month for Team, up to 100 users | PROVIDER-CONFIRMED |
| iSpring LMS | Active user | GBP 5.41/user/month at 100 users; GBP 6,489/year | PROVIDER-CONFIRMED |
| Teachbase | Active learner | RUB 241/active learner/month at 50 learners; approximately RUB 144,670/year | PROVIDER-CONFIRMED |
| SOHO.LMS Kazakhstan | Employee capacity tier | KZT 44,990/month for 50; 83,990 for 100; 194,990 for 250; 310,990 for 500 with annual billing | PROVIDER-CONFIRMED |
| SafetyCulture | Seat type | USD 5/month for Lite and USD 24/month for Full with annual billing | PROVIDER-CONFIRMED |
| SOVA LMS Kazakhstan | Functional module | KZT 30,000/month for the distance-learning module | PROVIDER-CONFIRMED |
| MyTeam HR Kazakhstan | Employee count / full functionality | Individual calculation | PROVIDER-CONFIRMED |

### 4.1 Closest public KZT comparison

SOHO.LMS provides the clearest public Kazakhstan benchmark:

| Employees | Monthly price with annual billing | Effective price per employee/month |
|---:|---:|---:|
| 50 | KZT 44,990 | About KZT 900 |
| 100 | KZT 83,990 | About KZT 840 |
| 250 | KZT 194,990 | About KZT 780 |
| 500 | KZT 310,990 | About KZT 622 |

### 4.2 Kazakhstan mandatory-training market

Observed public prices for training-center services vary approximately as follows:

| Service | Observed public range per learner |
|---|---:|
| Industrial safety | KZT 2,500-15,100 |
| Fire safety | KZT 3,000-15,990 |
| Occupational safety | KZT 5,000-23,500 |
| Group training with instructor and documents | KZT 10,000-17,500 |
| Individual programs | From KZT 30,000 |

These services are not direct Kamilya equivalents. Their price may include an instructor, approved program, examination board, protocol, official certificate, in-person work, practical work, and training-center responsibility.

**INFERRED:** Kamilya platform access, Kamilya content, and legally significant third-party training must be separate commercial line items.

## 5. Proposed pricing architecture

Kamilya should use four separate commercial components:

1. Platform subscription.
2. Paid pilot credited toward an annual agreement.
3. Kamilya content licence.
4. Customer-specific content and implementation services.

Official training, an examination board, practical procedures, or official documents must be quoted separately through an appropriately qualified provider when required.

## 6. Proposed platform prices

The following is a commercial hypothesis for annual prepayment. Tax treatment is **NOT VERIFIED** and must be stated according to the supplier's confirmed accounting status.

| Plan | Employee capacity | Proposed monthly price | Proposed annual price | Effective maximum price per employee/month |
|---|---:|---:|---:|---:|
| Start | Up to 50 | KZT 59,000 | KZT 708,000 | KZT 1,180 |
| Team | Up to 100 | KZT 99,000 | KZT 1,188,000 | KZT 990 |
| Business | Up to 250 | KZT 189,000 | KZT 2,268,000 | KZT 756 |
| Scale | Up to 500 | KZT 299,000 | KZT 3,588,000 | KZT 598 |
| Enterprise | More than 500 | From KZT 449,000 | Individual | Individual |

**INFERRED:** the recommended public starting statement is `Kamilya LMS from KZT 59,000 per month with annual payment`.

**INFERRED:** Start and Team carry a moderate premium over basic LMS hosting because Kamilya's intended value includes RU/KK operation, organizational structure, assignments, course and test drafting from customer documents, training records, product certificates, local support, and Kazakhstan-hosted operation. This positioning must be validated in paid sales.

## 7. Proposed platform inclusions

Core product functionality should not be artificially split across small plans. All paid plans should include the confirmed core product capabilities available at contract time:

- organization account;
- departments, positions, roles, and employee structure;
- standard employee import;
- course and test creation and publication;
- training assignment;
- completion records and training journal;
- product certificates;
- Russian and Kazakh user interface;
- standard technical support;
- standard administrator onboarding;
- ordinary product updates.

Plans should primarily differ by:

- employee capacity;
- included administrators;
- support scope and response target;
- implementation volume;
- integration requirements;
- dedicated-environment or SLA requirements.

Do not promise SSO, HRIS integration, a dedicated environment, or a special SLA until the exact implementation has passed a product and technical gate.

## 8. Proposed user-counting rule

Pure monthly-active-user billing is not recommended for recurring or mandatory training because activity may be highly seasonal and the customer's invoice would become unpredictable.

Proposed rule:

> The plan counts the maximum number of active employee accounts during the billing month. Archived and blocked former employees do not count.

Proposed included administrator capacity:

| Plan | Administrators included |
|---|---:|
| Start | 3 |
| Team | 5 |
| Business | 10 |
| Scale | 20 |
| Enterprise | By agreement |

Proposed temporary overage, allowed up to 20% of plan capacity:

| Plan | Additional employee/month |
|---|---:|
| Start | KZT 1,000 |
| Team | KZT 800 |
| Business | KZT 650 |
| Scale | KZT 550 |

If the overage continues for three consecutive months, the customer should move to the next plan.

## 9. Trial, demonstration, and paid pilot

### 9.1 Self-service trial

Proposed price: KZT 0.

Keep the current boundary:

- 14 days;
- up to 10 learners;
- up to 3 system users;
- 1 ordinary AI course generation;
- 1 job-description-based generation;
- no bank card.

The trial must not include manual methodological work by the Kamilya team.

### 9.2 Demonstration

Proposed price: KZT 0.

Proposed boundary:

- one meeting;
- demonstration environment;
- one small agreed document fragment;
- no full staff import;
- no complete production course;
- no production implementation;
- no commitment to preserve custom demonstration material.

### 9.3 Paid pilot

Proposed price: **KZT 150,000 for 30 calendar days**.

Proposed scope:

- up to 50 employees;
- one organization;
- one department, role, or selected group;
- limited organizational import;
- one agreed learning scenario;
- one draft course based on customer materials;
- one test;
- assignment and completion flow;
- training record review;
- final findings meeting.

If the customer signs an annual agreement within 30 days after the pilot, 100% of the pilot fee should be credited toward the first annual payment.

## 10. Proposed Kamilya content pricing

Platform subscription and content licence must be separate line items.

### 10.1 Ready Kamilya course

Proposed price:

- KZT 1,500 per employee per course for 12 months;
- minimum KZT 75,000 per organization and course.

| Employees | Proposed annual price for one course |
|---:|---:|
| 50 | KZT 75,000 |
| 100 | KZT 150,000 |
| 250 | KZT 375,000 |
| 500 | KZT 750,000 |

This model applies to internal digital learning that does not claim to provide an official state certificate or replace legally required procedures.

**OWNER-CONFIRMED:** the information-security course for financial organizations was assessed at approximately 70% content readiness during the discussion preceding this proposal.

**INFERRED:** it must not be sold as a completed content product until content completion, methodological review, wording review, application boundaries, and course version are confirmed.

### 10.2 Future content-library package

Do not sell an unlimited library until at least four courses are fully completed and approved.

Initial future hypothesis:

| Capacity | Proposed annual library price |
|---:|---:|
| Up to 100 employees | KZT 390,000 |
| Up to 250 employees | KZT 690,000 |
| Up to 500 employees | KZT 990,000 |

## 11. Customer-specific content services

| Service | Proposed price |
|---|---:|
| Adapt one course from usable customer materials | KZT 150,000-350,000 |
| Full methodological course production | KZT 500,000-1,200,000 |
| Additional language version | Additional 25-40% |
| Extended import and data cleanup | From KZT 100,000 |
| Large catalog migration | From KZT 150,000 |
| Additional administrator session | KZT 50,000/session |
| Non-standard integration | After technical estimate |
| Dedicated environment or special SLA | After technical estimate |

AI generation should not be sold to the customer as raw tokens. The customer purchases an agreed result and work scope.

## 12. Proposed discount policy

| Condition | Maximum proposed discount or adjustment |
|---|---:|
| Annual prepayment | Already reflected in list price |
| Monthly billing | 25% above annualized list price |
| Two-year prepaid agreement | Up to 10% |
| Initial bounded design-partner group | Up to 20% for the first year only |
| Ordinary sales discretion | Up to 10% |
| Discount above 15% | Product-owner approval required |
| Partner or 1,000+ employee volume | Individual review |

Proposed internal floor without a separate owner decision:

| Plan | Public hypothesis | Internal floor |
|---|---:|---:|
| Start | KZT 59,000 | KZT 49,000 |
| Team | KZT 99,000 | KZT 84,000 |
| Business | KZT 189,000 | KZT 160,000 |
| Scale | KZT 299,000 | KZT 254,000 |

Design-partner discounts must not be perpetual.

## 13. Proposed contract rules

- Price in KZT.
- Individual B2B agreement and invoice.
- No automatic consumer-style recurring charge unless separately approved and implemented.
- Exact employee capacity in the order form.
- Separate platform, content, implementation, and third-party-training line items.
- Explicit overage and archived-user rules.
- Explicit data export and retention terms.
- At least 60 days' notice before a renewal price change.
- No price change during an already paid term.
- Renewal review no more than once per year.
- Suggested renewal increase ceiling: official inflation or 10%, unless service scope expands.

## 14. Proposed landing position

Replace a completely opaque `Individual calculation` message with a non-binding starting point only after owner approval:

> **Working launch**  
> From KZT 59,000 per month with annual payment.  
> Final price depends on employee count, course content, implementation, and support scope.

The landing should continue to state that working access is provided to legal entities under an individually agreed B2B contract.

Do not publish the full five-plan matrix until paid-pilot evidence confirms the packaging.

## 15. Explicit non-goals

- No permanent free plan after the trial.
- No full custom content production in a free demonstration.
- No token-based customer pricing for AI generation.
- No unlimited manual support in a low-cost plan.
- No official-certificate claim for a Kamilya product certificate.
- No completed-product claim for a course that is not fully approved.
- No perpetual early-customer discount.
- No ad hoc customer price without an internal pricing matrix.
- No bundling of platform access with legally significant third-party training unless explicitly contracted.

## 16. Approval and validation gates

**Recommended status:** GO as a pricing hypothesis for the first 3-5 paid customers.

**Not recommended:** treating this document as a permanent approved price list before the following are verified:

- infrastructure cost per tenant;
- AI-generation cost and usage distribution;
- average support hours per tenant;
- onboarding and content-production labor;
- customer-acquisition cost;
- demonstration-to-pilot conversion;
- pilot-to-annual-contract conversion;
- gross margin by platform and service line;
- tax treatment and invoice wording;
- customer response to the KZT 59,000 public starting point.

Recommended review point: after three paid pilots or five signed annual customers, whichever comes first.

## 17. Open decisions for the next discussion

- Approve or change the KZT 59,000 public starting point.
- Decide whether the first paid pilot is KZT 150,000 or another amount.
- Confirm annual-prepayment and monthly-premium rules.
- Confirm active-account counting and overage treatment.
- Decide which completed course may become the first separately licensed Kamilya course.
- Confirm whether any customer segment needs a lower-capacity plan below 50 employees.
- Confirm tax wording before any price publication.
- Decide when to update the landing, commercial proposal, and order-form templates.

## 18. Sources

Official vendor and Kazakhstan market pages used on 2026-08-22:

- [TalentLMS pricing](https://www.talentlms.com/prices)
- [360Learning pricing](https://360learning.com/pricing/)
- [iSpring LMS pricing](https://www.ispring.com/pricing)
- [Teachbase pricing](https://teachbase.ru/tarify/)
- [Unicraft pricing](https://www.unicraft.org/page/tariff/)
- [SOHO.LMS Kazakhstan pricing](https://soholms.com/tariffs-kz)
- [SafetyCulture pricing](https://safetyculture.com/pricing/)
- [SOVA LMS pricing](https://sova-lms.kz/pricing)
- [MyTeam HR LMS](https://myteamhr.kz/solution/lms)
- [KCSO training prices](https://kcso.kz/price-list/educenter_price/)
- [Algorithm Progress training prices](https://progressa.kz/)
- [Tanym training](https://tanym-education.kz/)
- [KazPromEducation](https://prombezopasnost.kz/)

Provider prices may change. Refresh the benchmark before approving or publishing a price list.
