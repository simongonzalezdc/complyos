# Document Ingest (Solo-Owner On-Ramp) v0

> Working spec. Status labels follow `docs/learningops-suite-v0.md` (Live / Contract /
> Synthetic demo / Roadmap). Claim discipline in `ARCHITECTURE.md` applies verbatim:
> readiness / evidence / control-mapping language only — never "LMS-certified",
> "compliant", or any certification claim.

## Why this module exists

The smallest real buyers — solo and 1–2 person training/safety operators (e.g. a
construction-safety consultant) — do **not** run Workday, Cornerstone, or SuccessFactors.
Their source of truth is a folder of **Word programs, PDF certificates, and Excel rosters**.
Today ComplyOS can normalize an LMS export or a hand-built CSV; it cannot yet ingest the
messy documents these owners actually have.

This module is the **on-ramp that lets a document folder become a normalized,
renewal-aware training record + a client-facing evidence packet** — without the owner
owning an LMS. It is the wedge that makes ComplyOS fit the entire bottom of the market,
not only LMS-data shops.

It is framed as an **extension of the Live `Rosters` module** (a new document-source
adapter) plus a **light read surface** for normalized records, not a new monolith.

## What it is NOT (boundary — load-bearing)

This is **not an LMS** in the authoring/SCORM/seat-management sense, and we never call it
one in any surface. It does not author content, deliver courses, proctor, or certify.

It is a **normalized training-record + renewal-evidence surface**. The licensed human
(the owner) keeps the judgment, the authored content, the professional sign-off, and the
liability. See `docs/product-boundary-doctrine.md` — the software does the clerical layer;
the human keeps judgment, liability, and approval. That boundary is the product, not a
limitation to apologize for.

## Maturity map — what is already Live vs. the genuine delta

| Capability | Status today | Source |
| --- | --- | --- |
| Connector ABC (`get_users/courses/enrollments/learning_records`) | **Live** | `complyos/connectors/base.py` |
| CSV connector (reference impl: read → normalize → models) | **Live** | `complyos/connectors/csv_file.py` |
| Normalization helpers (alias remap, `parse_date`, `to_learning_status`, expiry) | **Live** | `complyos/connectors/normalization.py` |
| Import governance: Preview → Decide → Promote (quarantine, per-row decisions, evidence ledger, action log) | **Live** | `complyos/services/imports.py` |
| `LearningRecord` model incl. `expires_at` + `is_expired()` + `is_compliant` | **Live** | `complyos/models/domain.py` |
| Web shell Imports module (currently `csv_text` paste form) | **Live** | `complyos/web/shell.py` |
| Connector capability registry | **Live** | `complyos/connectors/capabilities.py` |
| **Document extraction** (`.docx`/`.xlsx`/`.csv` → table) | **NEW** | — |
| **File-upload UI + multipart route** (vs. paste) | **NEW** | — |
| **Client-facing evidence packet export** (learner · training · completed · renewal-due) | **NEW** | — |

The spine (governance, models, normalization, expiry logic, evidence ledger) already
exists. The honest delta is **~5 medium components**, no breaking changes, no new
permission model.

## Architecture (slots into existing flow)

```
upload .docx/.xlsx/.csv
        │
        ▼
DocumentExtractor (new) ──implements──▶ LMSConnector ABC
   extract table → reuse normalization aliases → User / Course / LearningRecord
        │
        ▼
ImportService.preview()  →  QUARANTINED batch        (existing, unchanged)
        │
        ▼
ImportService.decide()   →  per-row human accept/reject   (existing — the approval gate)
        │
        ▼
ImportService.promote()  →  evidence ledger + records      (existing, unchanged)
        │
        ▼
Records read view  +  Client Evidence Packet export   (new read/export surface)
```

Every promotion still writes a hashed `EvidenceLedgerEntry` and an action-log row. File
bytes are extracted to a table and hashed; the original document is **not** persisted to
disk by default (same posture as the CSV path).

## v0 scope (ship this first)

1. **DocumentExtractor connector** implementing `LMSConnector`.
   - Formats: **`.docx` + `.xlsx` + `.csv`** in v0. **PDF → Roadmap** (table extraction
     from PDF is the least reliable; do not block v0 on it).
   - Extract the first/primary table; fuzzy-map columns via the existing alias dictionaries
     (`USER_ALIASES`, `COURSE_ALIASES`, `ENROLLMENT_ALIASES`).
   - Target fields: learner id/email/name, training/course, status, completed_date,
     `expires_at` (renewal), optional score.
   - Read-only: `trigger_reminder()` returns `False` (same as CSV connector).
   - Fails closed: missing/unreadable table → preview surfaces an issue, never a silent
     partial promote.
2. **File upload in the shell Imports module.** Add a multipart `UploadFile` form alongside
   the existing paste field; route extracted rows into `ImportService.preview()`. Reuse the
   existing preview/decide/promote UI verbatim. (`python-multipart` is already a dependency.)
3. **Records read view.** A learner-scoped read of normalized records: who is trained, on
   what, completed when, **renewal due when**, what is expired/overdue. Reuse existing
   `LearningRecord` + `is_expired()`; no new model fields.
4. **Client Evidence Packet export.** Export a clean, client-facing artifact (CSV + minimal
   HTML): learner · training · completed_date · renewal_date · status. Readiness/evidence
   language only; no compliance assertion. Human approves before any client-facing send
   (`Approval Is Architecture`).

## New dependencies

- `python-docx` — Word `.docx` table extraction.
- `openpyxl` — Excel `.xlsx` extraction.
- `pdfplumber` — **Roadmap only** (PDF table extraction), not required for v0.

## Guardrails (must hold in every surface + doc)

- **No certification / compliance claims.** The `tests/unit/test_no_false_compliance_claims.py`
  guard applies to this module's docs, UI strings, and exports. Allowed: "normalized
  training records", "renewal-aware evidence", "readiness / control mapping",
  "client-facing status packet".
- **Quarantine before truth.** No file bypasses Preview → human Decide → Promote.
- **Human owns the sign-off.** The packet is evidence the owner presents; ComplyOS is never
  the authority of record.
- **Provenance preserved.** Raw-table hash + transformation steps recorded in the evidence
  ledger on every promote.

## Non-goals for v0

- No content authoring, SCORM, course delivery, proctoring, or seat management.
- No PDF extraction (Roadmap).
- No learner self-service login (the records view is operator-scoped in v0).
- No regulated-data guarantee, no automatic external send, no autonomous assignment.

## v0 success criteria

- `.docx`/`.xlsx`/`.csv` upload → extracted table → `User`/`Course`/`LearningRecord` with
  the same shape the CSV connector produces.
- Upload flows through unchanged Preview → Decide → Promote, writing evidence ledger +
  action log.
- Records view shows completion + renewal-due + expired correctly (driven by `expires_at`).
- Client Evidence Packet exports cleanly in readiness language; claim-discipline test green.
- Connector + import-governance + expiry + claims tests green against the local suite
  baseline (do not hard-code a stale test count).
