# RegWatch v0

RegWatch is the proposal-only regulatory intelligence capability for
LearningOps Suite. It watches official or authoritative sources, records
coverage gaps, and drafts training-impact alerts for human legal/compliance/L&D
review. It does **not** decide legal meaning, mutate ComplyOS rules, assign
training, or notify learners without explicit approval.

## Scope

RegWatch v0 answers four operational questions:

1. **What changed or may change?** Capture a source-backed regulatory signal.
2. **Where did it come from?** Store source URL, jurisdiction, agency, checked
   timestamp, parser status, and coverage gaps.
3. **Could this affect training?** Draft a relevance rationale and
   training-impact brief.
4. **Who approved action?** Keep a human-review state before any ComplyOS rule,
   MicroLearn suggestion, training assignment, or notification changes state.

## Source priority

1. Official APIs from government or regulatory bodies.
2. Official search pages, RSS feeds, PDFs, and agency pages.
3. Authoritative standards bodies or official publications offices.
4. Secondary legal/compliance commentary only as enrichment, never as the sole
   source for a rule proposal.

## Source registry requirements

Every source registry entry must include:

- `source_id`
- `source_name`
- `jurisdiction`
- `jurisdiction_level`
- `agency_or_body`
- `source_type`
- `primary_url`
- `api_or_feed_url`
- `access_model`
- `parser_status`
- `domain_tags`
- `last_verified_at`
- `coverage_notes`
- `known_gaps`
- `human_owner_role`
- `allowed_outputs`

The initial registry lives in
[`regwatch-source-registry.example.json`](./regwatch-source-registry.example.json).
It is an example contract, not a claim that all parsers are implemented.

## Initial official-source registry

| Source | Jurisdiction | Type | Why it matters | v0 status |
| --- | --- | --- | --- | --- |
| Federal Register API | US federal | API | Proposed/final rules, notices, agency metadata. | No-paid client implemented; pagination/filter hardening pending. |
| eCFR API | US federal | API | Current CFR text and point-in-time lookup for codified rules. | No-paid search client implemented; full-section/diff hardening pending. |
| Regulations.gov API | US federal | API | Dockets, proposed rules, comments, supporting material. | Candidate source; API key required. |
| OSHA laws/regulations | US federal safety | Official web pages | Safety-training and workplace compliance source discovery. | Candidate source; page parser pending. |
| California DIR/DLSE | US state | Official web pages | State employment/labor training relevance placeholder. | Placeholder source; page parser pending. |
| EUR-Lex webservice / search | EU/global | API/search | EU legal acts, directives, regulations, CELEX identifiers, XML output. | Placeholder source; registration/SOAP support required. |

## Shared Source Intelligence engine

RegWatch v0 now uses the shared [Source Intelligence Engine](./source-intelligence-engine-v0.md)
with MicroLearn Radar. RegWatch is the compliance/legal policy adapter over the
same source registry, snapshot, content-hash, signal, proposal, and human-review
primitives used for microlearning suggestions.

This matters operationally: one official source snapshot can create a RegWatch
obligation proposal and a MicroLearn draft-module proposal without duplicating
source capture or losing provenance. The shared engine is implemented/tested;
live crawling, scheduler jobs, and jurisdiction-specific parsers remain roadmap
until separately built and verified.

## Proposal-only workflow

```text
source registry
  → source check run
  → normalized source item
  → RegWatch alert proposal
  → human legal/compliance/L&D review
  → approved action packet
  → optional ComplyOS rule proposal, MicroLearn suggestion, or training-impact brief
```

No step after “RegWatch alert proposal” is automatic. The proposal may be
rejected, archived, escalated, or approved with edits.

## Approval states

| State | Meaning | Allowed next action |
| --- | --- | --- |
| `draft_detected` | Source item collected but not reviewed. | Enrich metadata or discard. |
| `triage_needed` | Potential relevance but no owner decision yet. | Assign reviewer. |
| `under_review` | Human reviewer is evaluating source and impact. | Request more context, reject, or approve with edits. |
| `approved_for_brief` | Human approved a training-impact brief only. | Create brief; no rule mutation. |
| `approved_for_rule_proposal` | Human approved a ComplyOS rule-change proposal. | Create pending rule proposal; still needs normal rule approval. |
| `approved_for_microlearn` | Human approved a MicroLearn suggestion. | Draft microlearning candidate; still needs SME approval. |
| `rejected` | Not relevant or not actionable. | Archive with reason. |
| `superseded` | Replaced by later source/item. | Link to successor. |

## Human review gates

RegWatch requires human approval before:

- changing a ComplyOS requirement/rule;
- publishing or assigning training;
- sending learner or manager notifications;
- marking a client, employee, or student as compliant/non-compliant;
- turning a source item into a MicroLearn module;
- using an interpretation in customer-facing material.

## Coverage-gap behavior

Every output must show coverage gaps. Examples:

- “Federal Register/eCFR checked; OSHA web parser not yet implemented.”
- “California source is placeholder-only; no state-level automated parser.”
- “EUR-Lex requires registered SOAP access; this run used metadata only.”
- “Source text was collected, but training relevance is low-confidence.”

## Fit with ComplyOS

RegWatch feeds ComplyOS by proposing reviewed source-backed changes. ComplyOS
remains the evidence engine. ComplyOS rules should only change through existing
approval/service workflows, never directly from a RegWatch source check.



## Current no-paid implementation surface

RegWatch can now use the shared source-intelligence runtime without paid APIs:

- `complyos source-intel sources --json` lists free/public sources and parser gaps.
- `complyos source-intel run-fixture --json` runs a no-network official-source fixture through RegWatch and MicroLearn adapters.
- `complyos source-intel run-public --dry-run --json` previews implemented public API calls.
- `complyos source-intel run-upload <file> --json` processes approved local source text when APIs are blocked.
- `complyos source-intel review --json` lists or decides local JSONL review proposals.
- `complyos source-intel schedule-add --db complyos.db --name daily-training-watch --json` creates a local schedule.
- `complyos source-intel run-scheduled --db complyos.db --force --json` records durable job executions.
- `complyos source-intel export-packet --db complyos.db --output packet.json --json` exports review/audit evidence.
- `complyos notifications drain --db complyos.db --dry-run --json` previews queued email, Slack-compatible, Teams-compatible, and customer webhook deliveries.
- `complyos notifications preference-set --db complyos.db --channel email --event-type audit.completed --disabled --reason "quiet hours" --json` sets tenant/channel kill switches.
- `POST /api/v1/hooks/inbound/{source}` stores a signed, redacted inbound receipt before any provider-specific parser is built.
- `/source-intel/review` shows the human review queue in the dashboard app.

The implemented clients cover Federal Register and eCFR contracts. OSHA, California,
state agency pages, Regulations.gov, and EUR-Lex remain parser/API-registration work.
