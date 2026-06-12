# ComplyOS incident tabletop template

Status: readiness artifact, not completed tabletop evidence.
Owner: security/privacy/legal review.
Review cadence: every 6-12 months and after major security architecture changes.

## Purpose

This Incident tabletop template gives ComplyOS a repeatable exercise format for testing breach response, security escalation, customer notification decisions, and post-incident learning.

## Scenario

Example scenario:

> An operator discovers that a privacy export or report may have included another tenant’s personal data. The team must confirm scope, contain access, preserve evidence, decide notification obligations, and prevent recurrence.

## Participants

Record:

- incident commander;
- engineering lead;
- security/privacy owner;
- customer/support owner;
- legal/counsel reviewer;
- communications owner;
- observer/note taker.

## Exercise prompts

1. What signal triggered the incident?
2. Who declares severity?
3. What logs/evidence are preserved?
4. How is tenant scope determined?
5. What access is revoked or contained?
6. Who approves customer/regulator notification language?
7. What is the customer update cadence?
8. What is the recovery/validation path?

## Evidence to retain

- date/time;
- Participants;
- Scenario tested;
- timeline;
- decisions;
- gaps found;
- owners;
- Lessons learned;
- follow-up due dates.

## Post-exercise actions

- update breach-response runbook;
- update monitoring/alerting gaps;
- update DSR/export safeguards if relevant;
- create remediation tickets;
- attach summary to security evidence packet.
