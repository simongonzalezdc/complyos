# Demo: Fix messy existing training operations

**Scenario:** a training coordinator receives inconsistent LMS/HRIS exports,
spreadsheets, and follow-up requests. The buyer wants a clean path from messy
records to gaps, drafts, manager/client reporting, and evidence packets.

**Data status:** synthetic demo only. No real employee, student, client, or
employer data.

## Modules shown

| Step | Module | Maturity | Output |
| --- | --- | --- | --- |
| 1 | CSV fallback / Intake | Live + Synthetic demo | Messy upload with source metadata. |
| 2 | Rosters | Synthetic demo | Normalized learner/course/completion records. |
| 3 | ComplyOS | Live | Gap and exception analysis. |
| 4 | RegWatch | Contract | Optional changed-requirement alert if profile matches. |
| 5 | Learner Support | Synthetic demo | Draft follow-up messages. |
| 6 | Manager Briefs | Synthetic demo | Status, exceptions, and next actions. |
| 7 | EvalOps | Synthetic demo | Survey themes and program feedback. |
| 8 | ComplyOS | Live | Evidence packet: source → record → rule/source → action → approval → packet. |

## Demo path

1. Load
   `examples/learningops-suite/fix-messy-training-ops/messy-lms-export.csv`.
2. Preview quarantine reasons:
   - duplicate learner ids;
   - mixed status casing;
   - stale completion date;
   - missing source record id;
   - conflicting course title.
3. Compare with `normalized-roster.csv` to show the proposed clean record set.
4. Open `gap-analysis.json` for completion gaps, expired records, exceptions,
   and evidence chain.
5. Open `learner-support-drafts.json` to show draft-only learner follow-up.
6. Open `manager-brief.json` to show status, risk, next actions, and coverage
   disclosure.
7. Stop at the approval gate before sending messages or changing records.

## Approval gate

Before state changes, a human reviewer must approve:

- whether the normalized records are accurate;
- whether exceptions should be accepted, remediated, or escalated;
- learner follow-up copy;
- manager/client brief;
- any ComplyOS evidence packet release.

## What this proves

- The suite can start from CSV when APIs are unavailable.
- Messy records become auditable proposals, not silent mutations.
- ComplyOS remains the proof/evidence engine.
- Manager and learner communication can be drafted without auto-sending.

## What this does not prove

- It does not prove direct Workday, Cornerstone, SuccessFactors, or Canvas API
  access for this specific tenant.
- It does not prove automated employment decisions.
- It does not prove all jurisdictions or all LMS exports are covered.

