# ComplyOS AI impact assessment

Status: readiness artifact, not legal advice.
Owner: product/security + privacy/legal review.
Review cadence: every AI feature, model change, or new customer region.

## Purpose

This AI impact assessment defines the safe lane for ComplyOS AI features in HR/L&D, people analytics, and education-adjacent workflows.

## Proposal-only boundary

ComplyOS AI is **Proposal-only** unless a future reviewed workflow explicitly says otherwise.

Current AI may:

- suggest field mappings from headers or redacted metadata;
- generate metadata/provenance for human review;
- help operators draft remediation plans.

Current AI must not:

- mark a learner or employee as compliant/non-compliant without deterministic records;
- promote imports;
- change rules;
- send notifications;
- change evidence truth;
- make or recommend employment, discipline, compensation, promotion, termination, eligibility, or opportunity decisions.

## Human review

Human review is required before any AI proposal affects operational state. Review evidence should include:

- proposal ID;
- model/provider metadata;
- prompt/response hashes or equivalent provenance;
- reviewer ID;
- approval/rejection timestamp;
- reason or ticket reference where material.

## Employment decision boundary

ComplyOS is training-evidence automation. It is not an automated employment decision product.

Danger zone requiring counsel/product review:

- ranking employees or applicants;
- predicting job performance;
- recommending discipline, termination, compensation, promotion, or eligibility;
- using training data as a background-screening report;
- using AI output to deny access to opportunity.

## Risk assessment checklist

Before shipping an AI feature, answer:

1. What input data categories are used?
2. Does the feature touch worker, learner, student, or protected-class context?
3. Can output affect a person’s job, school, credential, compensation, or opportunity?
4. Is the output explainable with source records and evidence hashes?
5. Does a human approve before state changes?
6. Is there a way to appeal or correct the underlying data?
7. What jurisdictions/customers are in scope?
8. What logs prove review and provenance?

## Required evidence before production use

- approved product boundary;
- model/provider risk review;
- human-review workflow;
- testing for incorrect mappings and unsupported state mutation;
- customer disclosure language where required;
- escalation workflow for buyers requesting people-decision use.

## Current implementation refs

- `complyos/services/ai_proposals.py`
- `tests/unit/test_ai_proposals.py`
- `tests/unit/test_mcp_enterprise.py`
- `docs/hr-people-analytics-compliance-audit.md`
