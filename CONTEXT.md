# ComplyOS Context

## What ComplyOS Is

ComplyOS is a learning-compliance evidence engine. It ingests learning data from
CSV exports and LMS connectors, normalizes that data into one shared audit model,
and produces evidence-backed compliance gaps and audit trails.

ComplyOS has two buyer tracks:

- **Workforce** — employee training compliance for L&D, People Ops, HRIS, and
  security compliance teams.
- **Campus** — student, program, district, and higher-ed requirement tracking for
  academic technology and compliance teams.

Both tracks use the same audit model. The terms differ by market, but the engine
still asks the same question: which learners lack valid evidence for required
learning items?

## Domain Glossary

| Term | Meaning |
|------|---------|
| **Learner** | The person whose learning compliance is audited. In Workforce this is usually an employee. In Campus this is usually a student. Current code stores learners as `User`. |
| **Learning Item** | The required learning object. It may be a course, module, training, assignment, certification, or requirement depending on the source system. Current code stores learning items as `Course`. |
| **Learning Record** | A normalized cross-LMS source record that says what happened between one learner and one learning item: assignment, enrollment, submission, completion, exemption, score, due date, or expiry. Current code has a `LearningRecord` model for connector normalization. |
| **Enrollment** | The current audit-engine compatibility model for a learner's relationship to a course. It is intentionally narrower than `LearningRecord`, but remains supported so the existing auditor and reports keep working. |
| **Compliance Gap** | A missing, incomplete, overdue, expired, or otherwise invalid requirement for a learner. Current code stores gaps as `ComplianceGap`. |
| **Evidence Ledger** | The immutable audit trail that hashes raw inputs, transformation steps, and audit outputs so reports can be defended later. Current code stores entries as `EvidenceLedgerEntry`. |
| **Workforce** | The ComplyOS profile for employee learning-compliance operations. Typical source systems include Workday Learning, Cornerstone OnDemand, SAP SuccessFactors Learning, Docebo, Absorb, Litmos, and CSV exports. |
| **Campus** | The ComplyOS profile for education compliance operations. Typical source systems include Canvas, Brightspace, Blackboard, Moodle, Schoology, Google Classroom, and CSV exports. |

## Relationships

```text
Learner ── has ──▶ LearningRecord ── for ──▶ Learning Item
   │                    │                         │
   │                    ▼                         │
   └──────── audited by shared rules ─────────────┘
                         │
                         ▼
                  ComplianceGap[]
                         │
                         ▼
                  EvidenceLedger
```

- A **Learner** can have many **Learning Records**.
- A **Learning Item** can appear in many **Learning Records**.
- Each **Learning Record** ties one learner to one learning item and preserves
  source-system evidence such as source IDs, due dates, scores, exemptions, and
  expiry dates.
- The audit engine reads normalized learner, learning item, and record data to
  find **Compliance Gaps**.
- Every audit writes an **Evidence Ledger** entry with hashes of the inputs and
  outputs.

## Example Dialogue

> **Operator:** Canvas calls this an enrollment and Cornerstone calls it a
> transcript item. Are those different things in ComplyOS?
>
> **ComplyOS:** They are different source-system shapes, but they normalize to
> the same `LearningRecord` contract.
>
> **Operator:** So a Canvas enrollment for FERPA and a Cornerstone transcript for
> security training can use one audit model?
>
> **ComplyOS:** Yes. Canvas, Cornerstone, and CSV exports keep their source IDs
> and payload evidence, then map assignment/completion/exemption/due-date/expiry
> data into `LearningRecord`. The existing `Enrollment` model remains available
> as the compatibility layer for the current audit engine.

## Flagged Ambiguities

- **`BSL` is ambiguous.** Use `BUSL-1.1` when referring to Business Source
  License 1.1. `BSL-1.0` usually means the unrelated Boost Software License.
- **`Enrollment` is too narrow for cross-LMS language.** Some systems expose
  transcripts, assignments, submissions, completions, exemptions, or
  recertifications instead of enrollments. Use `LearningRecord` in connector and
  cross-market documentation.
- **`Course` is acceptable in current code.** The implementation still uses
  `Course`, but cross-market docs should prefer **Learning Item** because
  Workforce and Campus systems do not always call the required object a course.
