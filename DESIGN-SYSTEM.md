# ComplyOS / LearningOps Suite design system

## North star

**Enterprise evidence console, not SaaS confetti.** The interface should feel like
the shared admin grammar behind Workday, Cornerstone, SuccessFactors, Canvas, and
Bloomberg Terminal: dense enough for operators, calm enough for buyers, explicit
about source systems, statuses, exceptions, approvals, and evidence packets.

## Audience and job

- HR, L&D, training, safety, security, campus, and client-delivery operators.
- Buyers who already live in LMS/HRIS admin tools.
- People who need proof, not “AI magic”: source → record → rule/source →
  action → approval → packet.

## Competitor-derived defaults

The visual language is prefilled from enterprise systems the product integrates
with:

- **Workday:** worker, manager, organization, role, and status vocabulary.
- **Cornerstone / SuccessFactors:** learning object, transcript, assignment,
  completion, exception, and approval language.
- **Canvas / LMS tools:** course, enrollment, cohort, assignment, completion, and
  gradebook-style record tables.
- **Bloomberg Terminal:** information density, operator confidence, timestamped
  records, and low decorative noise.

## Aesthetic territory

- Low-gloss operations console.
- Warm paper background with green-black evidence surfaces.
- Amber used as review/provenance accent, not decoration.
- Rounded but not toy-like: controls 8-10px, cards 22-30px, tags may be pill.
- No purple gradients, floating blobs, emoji headings, glass-card default, or
  generic centered-hero/three-card SaaS skeleton.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--paper` | `#f6f7f1` | Page background. |
| `--paper-strong` | `#ffffff` | Dense surfaces and cards. |
| `--ink` | `#171b18` | Primary text. |
| `--muted` | `#5b655d` | Secondary text. |
| `--line` | `rgba(23, 27, 24, 0.13)` | Standard dividers. |
| `--line-strong` | `rgba(23, 27, 24, 0.24)` | Controls and emphasized borders. |
| `--accent` | `#3d7052` | Evidence/system accent. |
| `--accent-dark` | `#213f2f` | Primary action and dark surfaces. |
| `--accent-soft` | `#dbe8dc` | Tags and status fills. |
| `--amber` | `#b5762b` | Review/provenance/focus accent. |
| `--warm` | `#e8dfcf` | Warm neutral panels. |
| `--danger` | `#7d3f36` | Claim-boundary risk. |

## Typography

- Body: system UI stack for enterprise-app familiarity and zero layout shift.
- Display: same stack, pushed with strong size/weight/letter-spacing contrast.
- Mono: `ui-monospace`, used for source ids, timestamps, evidence hashes, and
  operator metadata.
- Body copy maxes around 66-72ch; admin boards and cards can be denser.

## Layout grammar

- Asymmetric grids over centered-only marketing sections.
- Boards, rows, ledgers, and matrices over decorative card farms.
- Every major section should answer an operator question:
  - What is live?
  - What is draft?
  - Which source system?
  - What needs approval?
  - What packet proves it?

## Component rules

- Buttons: 8-10px radius, hover, active, and `:focus-visible`.
- Links: visible hover/focus state; no hidden important links.
- Tags/status pills: allowed to be pill-shaped if they behave like labels, not
  primary CTAs.
- Matrices: use borders and label chips; avoid heavy shadows.
- Demo surfaces: every synthetic/demo artifact must label itself as synthetic,
  demo, or roadmap when applicable.

## Motion

- Restrained entrance animation only.
- Respect `prefers-reduced-motion: reduce`.
- No animated blobs, parallax, or constant movement.

## Copy voice

- Direct, operator-first, proof-first.
- Say “readiness,” “control mapping,” “proposal,” “draft,” “review,” and
  “evidence packet.”
- Do not imply certification, legal status, auto-assignment, auto-sending, or
  production integration where the capability is synthetic/contract/roadmap.

## Signature move

Every page should expose the chain:

```text
source → record → rule/source → action → approval → packet
```

If a surface cannot show that chain or explain its maturity label, it is not
ready to ship.

