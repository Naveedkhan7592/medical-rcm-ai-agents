# Appeal Specialist Agent

The Appeal Agent prepares evidence-based appeal drafts for human review. It does not submit appeals, contact payers, modify claims, change codes, post financial changes, or predict appeal outcomes.

## Architecture

The agent consumes synthetic claim and denial records plus existing deterministic specialist results:

- Denial Agent classification and evidence
- Billing QA status and conflicts
- Coding, Eligibility, Payment, and A/R evidence
- Rules Engine results
- Synthetic payer policy and claim history when available

The deterministic Appeal Agent result remains authoritative. The optional LLM can improve explanation readability, but it cannot change readiness, denial category, evidence, financial values, or policy facts.

## Readiness

- `READY_FOR_REVIEW`: claim, denial, known category, payer policy, Billing QA pass, and category-specific support are available.
- `NOT_READY`: claim/denial identity or required category-specific support is missing.
- `REVIEW`: denial category is unknown, payer policy is unavailable, Billing QA requires review, or the case involves medical necessity/high-risk uncertainty.

Every result sets `human_review_required=true`, including ready drafts.

Authorization and documentation support must be explicitly supplied; denial wording alone is not treated as proof of authorization or documentation. Medical necessity cases remain human-review cases and never receive invented clinical facts.

## Evidence and draft

Evidence is source-attributed and limited to available deterministic facts from claim, denial, specialist agents, payer policy, history, and Rules Engine. The draft uses neutral language: it requests review of the documented denial and evidence without asserting payer error or promising payment.

Missing information is structured with the item, reason, required purpose, source check, and severity. No authorization number, diagnosis, code, policy term, or documentation is fabricated.

## LLM boundary

The LLM may summarize evidence, explain missing information, and suggest questions for a human reviewer. It cannot change denial category, readiness, Billing QA status, payment amounts, A/R balance or aging, coding, eligibility, payer policy, or appeal outcome. LLM explanation is stored separately from deterministic evidence.

## Audit events

- `appeal_check_started`
- `appeal_claim_loaded`
- `appeal_denial_loaded`
- `appeal_evidence_collected`
- `appeal_policy_checked`
- `appeal_readiness_evaluated`
- `appeal_missing_information_identified`
- `appeal_draft_generated`
- `appeal_llm_reasoning`
- `appeal_result_generated`

Audit data is concise and excludes API keys, secrets, full patient records, and unnecessary member IDs.

## Testing and limitations

Tests inject deterministic fake collaborators and a fake LLM. They require no PostgreSQL, Docker, network, OpenAI API, payer API, eClinicalWorks, or external submission system.

All healthcare data and policies are synthetic/demo data. This implementation is not production healthcare deployment and makes no HIPAA compliance claim. Future RCM Supervisor or n8n layers may orchestrate human approval, but this agent does not perform that workflow.
