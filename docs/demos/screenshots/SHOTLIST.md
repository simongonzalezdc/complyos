# ComplyOS live shell — demo shot list

Screenshots of the live ComplyOS web console (the `/shell` evidence console),
captured at 1440×900 against a throwaway SQLite database seeded with **synthetic
data only** (no real workers, learners, or client records). ComplyOS is
readiness and evidence tooling: it surfaces training gaps, renewals, and an
audit trail for human review. It does not assert that any organization is
"compliant" or "certified" — those determinations stay with the client and their
counsel.

Console login runs in insecure-local mode (role picker, no token) purely for the
demo; production deployments require an API token or signed session.

| # | File | Module / view | What a buyer sees |
|---|------|---------------|-------------------|
| 01 | `01-overview.png` | Overview | Posture tiles — open gaps, high-risk gaps, readiness controls designed, source signals awaiting review — plus a gaps-by-severity breakdown. |
| 02 | `02-gaps.png` | Gaps | Worker compliance-gap queue from the audit service: missing required training, days overdue, and severity, most severe first. |
| 03 | `03-imports.png` | Imports | Paste-CSV or upload-a-document intake form (Word/Excel/CSV), with the note that unexpected columns are flagged, not silently dropped. |
| 04 | `04-imports-preview.png` | Imports — preview | A live preview run: rows quarantined for reviewer decision, backdated-date validation warnings, per-row accept/reject controls, and a fail-closed "promote blocked" state. |
| 05 | `05-records.png` | Records | Renewal-aware normalized training records — learner, training, completion date, renewal-due date, expired flag, and status — with CSV/HTML export controls. |
| 06 | `06-evidence.png` | Evidence | Append-only evidence ledger: each audit and import action pinned to a tamper-evident hash with a plain-language summary. |
| 07 | `07-remediation.png` | Remediation | Dry-run remediation proposal — the reminders and follow-ups that *would* run — with an explicit note that nothing is sent, enrolled, or notified without separate approval. |
| 08 | `08-source-intelligence.png` | Source intelligence | Regulatory and microlearning signal queue proposed for human review; accept/reject decisions never mutate rules or training on their own. |
| 09 | `09-privacy-retention.png` | Privacy & retention | Read-only privacy posture: active legal holds that block deletion and the tenant retention policy in days. |
| 10 | `10-readiness.png` | Readiness | Control-readiness matrix and data-governance metadata, labeled readiness-only — it maps controls and artifacts and does not claim SOC 2, FERPA, COPPA, or GDPR status. |
| 11 | `11-administration.png` | Administration | Tenant-scoped role bindings (actor → role) with the reminder that an admin can never see or change another tenant's assignments. |
| 12 | `12-client-evidence-packet.png` | Client status packet | The client-facing status packet rendered in-browser at `/shell/records/export.html` — a portable learner/training/renewal/status table ready to share. |

## How these were produced

1. Seed a throwaway DB from synthetic CSV exports: `COMPLYOS_CSV_DIR=<synthetic-dir>` then `complyos sync` and `complyos audit`.
2. Serve the console: `COMPLYOS_ALLOW_INSECURE_LOCAL=1 complyos serve-dashboard --host 127.0.0.1 --port 8123`.
3. Log into `/shell` as `owner` and capture each module.

All learner names and emails are fictitious (`example.com`); regulatory signals
are illustrative and marked as proposed-for-review, not legal determinations.
