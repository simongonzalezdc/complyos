# Product Boundary Doctrine

> Canonical positioning + claim boundary for ComplyOS and the LearningOps Suite.
> This is the value-prop form of `ARCHITECTURE.md` → Claim Discipline. Every surface,
> doc, demo, pitch, and piece of marketing copy must stay inside it.

## The one line

**The software does the clerical layer. The licensed human keeps the judgment, the
liability, and the approval.**

ComplyOS is a **readiness / evidence layer**, never the authority of record. It removes
the paperwork that steals a professional's billable hours; it never replaces the
professional, and it never certifies anything.

## The split (use this whenever someone asks "what's left for the human?")

| The software does (clerical, repeatable, hashable) | The human keeps (judgment, liability, relationship) |
| --- | --- |
| Ingest messy sources (LMS export, HRIS, CSV, Word/PDF/Excel) | The expert work itself — the inspection, the diagnosis, the field judgment |
| Normalize into clean, comparable records | Deciding what is actually needed for *this* case |
| Track who/what/when, flag renewals & gaps before they lapse | Authoring and owning the substantive content |
| Package a clean, client-facing evidence trail | **Signing it** — the name, the license, the liability on the artifact |
| Remember everything, lose nothing | The relationship and the call at 6am |
| Propose (drafts, mappings, anomalies) | **Approve** — every client-facing or truth-mutating step |

## Why this is the product, not a limitation

1. **It is the honest boundary.** ComplyOS genuinely is not a compliance, legal, or
   professional authority. Saying so is accurate, not modest.
2. **It is the trust wedge.** Buyers (and their clients) trust the artifact *because* a
   named human stands behind it. "AI-assisted, human-approved" is the selling point.
3. **It is the dream outcome.** The buyer's win is not "fewer of me" — it is *more clients
   per me, faster turnaround, sharper deliverables, fewer lapses that bite me later.* The
   software gives back the hours; the human keeps the margin.
4. **It is legally load-bearing.** It maps onto Claim Discipline and the
   `test_no_false_compliance_claims.py` guard. Drop the boundary and we manufacture
   liability and false claims in the same sentence.

## Language rules (enforced)

- **Never** "compliant", "certified", "guarantees compliance", "LMS-certified",
  "makes you audit-proof", "replaces your [LMS / consultant / admin]".
- **Always** "readiness", "control mapping", "evidence", "review", "normalized records",
  "renewal-aware", "client-facing status packet", "AI proposes, human approves".
- A test enforces the forbidden patterns at the codebase level
  (`tests/unit/test_no_false_compliance_claims.py`). Extend it when new claims appear.

## The buyer-facing one-liner

> "It does the paperwork. You're still the expert — you just look sharper and lose fewer
> hours doing it."

## Applies to

ComplyOS · every LearningOps Suite module (Live, Contract, Synthetic demo, Roadmap alike) ·
the Document Ingest on-ramp (`docs/document-ingest-v0.md`) · all PuenteWorks / KyaniteLabs
pitch + marketing copy that references the product.
