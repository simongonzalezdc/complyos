# LearningOps Suite v0

LearningOps Suite is the working-title umbrella for a modular set of HR,
training, L&D, compliance, and learning-operations tools. **ComplyOS remains
the implemented compliance/evidence module inside that suite.** The suite frame
exists so buyer conversations can start from the full job-to-be-done without
pretending every future module is already production software.

## Decision summary

- **Chosen model:** brand now, integrate later.
- **Implemented core today:** ComplyOS learning-evidence, readiness, privacy,
  security packet, CLI/API/MCP, CSV fallback, and connector-profile workflows.
- **Near-term extension:** a shared Source Intelligence engine that powers
  proposal-only RegWatch signals and MicroLearn Radar suggestions with
  official/source provenance and human approval gates.
- **Demo/spec modules:** instructional design, training specialist,
  microlearning, scheduling, rosters, learner support, evaluation, and manager
  briefs.
- **Non-goal:** do not collapse all modules into one premature monolith.

## Maturity labels

Use these labels everywhere the suite is described:

| Label | Meaning | Product promise |
| --- | --- | --- |
| **Live** | Implemented in this repository and covered by tests/docs. | Can be demoed as current product capability. |
| **Contract** | Typed/spec-level boundary is defined; runtime may be partial or pending. | Can be discussed as an integration contract or near-term build path. |
| **Synthetic demo** | Demonstrated with fake data and scripted artifacts only. | Can show workflow intent, not production availability. |
| **Roadmap** | Buyer-validated idea or planned module with no production promise yet. | Must be labeled as future or configurable work. |

## Buyer lanes

| Lane | Buyer problem | Entry modules | Proof required |
| --- | --- | --- | --- |
| **Corporate L&D / People Ops** | Training completion is scattered across LMS, HRIS, spreadsheets, and manager follow-up. | ComplyOS, Rosters, Scheduling, Learner Support, Manager Briefs. | Source system, normalized record, gap rule, action log, reviewer approval, evidence packet. |
| **Regulated workforce training** | New or changed requirements create uncertainty about who needs training and what proof is enough. | RegWatch, ComplyOS, NeedsAnalysis, ObjectiveBuilder, FacilitationOps. | Official source, coverage note, training-impact rationale, human approval, evidence packet. |
| **Training provider / client delivery** | External clients want status, exceptions, certificates, and clean follow-up without manual spreadsheet work. | Intake, Rosters, EvalOps, Manager Briefs, ComplyOS. | Client-facing status packet, exception log, CSV/API import receipt, export metadata. |
| **Schools / campus readiness** | Campus teams need privacy/accessibility/vendor evidence without overclaiming legal status. | ComplyOS campus profile, privacy workflows, school vendor packet, accessibility packet. | DSR workflow, vendor evidence, access/a11y documentation, review trail. |

## Module taxonomy

| Module | Maturity | Primary user | Role in the suite | Required guardrail |
| --- | --- | --- | --- | --- |
| **ComplyOS** | Live | HR, L&D, security, campus ops, auditors | Compliance evidence engine: gaps, packets, tenant-scoped audit logs, retention/DSR, readiness controls. | Readiness/control mapping only; no certification or legal-status claim. |
| **RegWatch** | Contract | Legal/compliance, L&D owners | Monitors official-source regulatory changes through the shared Source Intelligence engine and creates proposal-only relevance/training-impact alerts. | No rule mutation without human approval. |
| **Source Intelligence** | Live | Product operator, compliance owner, instructional designer | Shared source registry/snapshot/signal/proposal spine for RegWatch and MicroLearn Radar; deterministic adapters are implemented and tested. | No crawler or adapter may publish, assign, notify, or mutate rules without approval. |
| **Intake** | Live | Training coordinator, business requester | Captures requests, missing info, priority, audience, constraints, and routing. | Human owner confirms scope before work starts. |
| **Scheduling** | Synthetic demo | Training coordinator | Cohorts, sessions, rooms/links, reminders, waitlists, and reschedules. | Human-approved rollout plan before notifications. |
| **Learner Support** | Synthetic demo | Training specialist, coordinator | Drafts learner follow-up, escalation notes, and missing-completion nudges. | Draft-only messaging until a human sends or approves. |
| **Rosters** | Synthetic demo | Training coordinator, L&D analyst | Normalizes attendance/enrollment/completion records across LMS, HRIS, and CSV exports. | Quarantine/preview before imports mutate truth. |
| **MicroLearn Radar** | Roadmap | Instructional designer, training specialist | Uses the shared Source Intelligence engine to find source-backed topic suggestions and draft microlearning candidates after approval. | Source quality scoring and SME approval before publication. |
| **NeedsAnalysis** | Synthetic demo | Instructional designer, L&D partner | Determines whether training is the right intervention and captures the performance gap. | Explicit “training may not be the fix” outcome. |
| **ObjectiveBuilder** | Synthetic demo | Instructional designer | Converts needs into measurable learning objectives and assessment alignment. | SME review before objectives become course requirements. |
| **StoryboardStudio** | Synthetic demo | Instructional designer | Drafts lesson/module outlines, SME review packets, and microlearning structure. | Draft-only until SME approval. |
| **AssessmentBuilder** | Synthetic demo | Instructional designer, trainer | Drafts knowledge checks, scenarios, rubrics, and completion criteria. | Human review for fairness, role fit, and accessibility. |
| **JobAid Studio** | Roadmap | Training specialist, field enablement | Creates SOPs, checklists, one-pagers, and bilingual quick references. | Accessibility and localization review before release. |
| **FacilitationOps** | Synthetic demo | Facilitator, training specialist | Produces facilitator guide, run-of-show, materials checklist, and session readiness. | Trainer confirms materials and logistics. |
| **TrainTheTrainer** | Roadmap | Program owner, lead trainer | Trainer prep, observation checklist, coaching rubric, and calibration notes. | Observation evidence kept separate from employment decisions unless reviewed. |
| **SessionCommand** | Roadmap | Facilitator, coordinator | Live attendance, participation notes, issue log, parking lot, and post-session tasks. | Privacy-minimized notes and retention policy. |
| **SkillsCheck** | Roadmap | Trainer, supervisor, quality lead | Competency checklist, observation rubric, remediation plan. | FCRA/employment-decision boundary if used for worker consequences. |
| **EvalOps** | Synthetic demo | L&D analyst, program owner | Survey analysis, themes, instructor/program comparison, and improvement backlog. | Aggregate/suppress small groups to reduce privacy risk. |
| **ImpactBriefs / Manager Briefs** | Synthetic demo | L&D analyst, client success, managers | Leadership/client summaries, status packets, risk/exceptions, and next actions. | Evidence-backed claims only; separate facts from recommendations. |

## ComplyOS as the compliance/evidence module

ComplyOS should stay focused on the evidence workflow:

1. Import source records through CSV, mock, or connector profiles.
2. Preview and quarantine questionable data.
3. Normalize records to tenant-scoped evidence.
4. Apply configured readiness rules.
5. Produce gaps, exceptions, packets, DSR/retention/security evidence, and audit logs.
6. Expose the same service-backed actions through CLI, API, and MCP.

The suite can call ComplyOS, but ComplyOS should not need speculative suite
modules to stay useful. This preserves the current product and keeps the suite
modular for buyers who only need evidence/compliance.

## Source Intelligence placement

RegWatch and MicroLearn Radar are not two separate crawlers. They share one
source-intelligence spine:

1. registered source or approved upload;
2. content-hashed snapshot;
3. adapter scoring;
4. proposal packet;
5. human approval gate.

The implemented v0 slice is deterministic and test-covered. It does not include
paid/keyed integrations, source-specific parsers, autonomous publication, or
claims that every jurisdiction is monitored. It now does include local
DB-backed schedules, execution receipts, review UI, and export packets, so the
production plumbing can be hardened before external API procurement. See
[Source Intelligence Engine v0](./source-intelligence-engine-v0.md).

## RegWatch placement

RegWatch is inside or adjacent to ComplyOS because regulatory changes only
matter operationally when they can become reviewed requirements, training
impact briefs, or evidence packets.

See the dedicated [RegWatch v0 design](./regwatch-v0.md),
[RegWatch data contracts](./regwatch-data-contracts.md), and
[example source registry](./regwatch-source-registry.example.json).

RegWatch v0 must track:

- jurisdiction;
- agency/source;
- official URL or API endpoint;
- source type;
- last checked time;
- parser/status;
- citation or identifier;
- effective/proposed date when available;
- relevance rationale;
- confidence;
- coverage notes and known gaps;
- human-review status.

RegWatch may draft alerts, training-impact briefs, MicroLearn candidates, or
ComplyOS rule-change proposals. It must not silently update compliance rules,
assign training, notify learners, or publish legal interpretation.

## Demo flows

### Demo 1: Training from scratch

Full packet: [`docs/demos/training-from-scratch.md`](./demos/training-from-scratch.md).

1. RegWatch or Intake flags a possible new training need.
2. NeedsAnalysis decides whether training is the right intervention.
3. ObjectiveBuilder proposes measurable objectives.
4. StoryboardStudio drafts a short module or microlearning outline.
5. MicroLearn Radar attaches source-backed support material.
6. AssessmentBuilder drafts checks for understanding.
7. FacilitationOps creates the facilitator/run-of-show packet.
8. Scheduling and Rosters prepare rollout and track assignment/completion.
9. ComplyOS produces evidence/readiness output if completion proof matters.

### Demo 2: Fix messy existing training operations

Full packet:
[`docs/demos/fix-messy-training-ops.md`](./demos/fix-messy-training-ops.md).

1. Import a messy CSV/LMS/HRIS export.
2. Rosters normalizes learners, courses, assignments, completions, and exceptions.
3. ComplyOS finds gaps, expired records, and evidence issues.
4. RegWatch flags a relevant changed/new requirement if configured.
5. Learner Support drafts follow-up and escalation messages.
6. Manager Briefs drafts status, risk, and next actions.
7. EvalOps summarizes feedback if survey data exists.
8. ComplyOS produces the source → record → rule/source → action → approval → packet trail.

## Interface principles

- **CSV fallback first-class:** every demo should work when enterprise API
  access is blocked, delayed, or politically impossible.
- **Official-source provenance:** regulation-aware flows cite official sources
  before secondary commentary.
- **Human approval before state change:** AI proposes; accountable humans
  approve rule changes, training publication, learner notifications, and client
  communications.
- **Evidence chain over dashboards:** every status surface should explain which
  source records, rules, actions, and approvals produced the result.
- **Maturity labels visible:** implemented, contract, synthetic demo, and
  roadmap capability must not be blended in sales or docs copy.

## Near-term build sequence

1. Keep ComplyOS stable as the live module.
2. Build and test the shared Source Intelligence primitives behind RegWatch
   and MicroLearn Radar.
3. Add RegWatch contracts and fixtures with source provenance and approval
   gates.
4. Build the two synthetic suite demos.
5. Refresh landing/docs to distinguish live, demo, and roadmap capability.
6. Let buyer pull decide which demo/spec modules become production runtime.
