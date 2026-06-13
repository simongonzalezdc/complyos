# Source Intelligence Engine v0

Source Intelligence is the shared ingestion, scoring, proposal, and approval
spine for RegWatch and MicroLearn Radar. The two product surfaces are different;
the underlying primitives are intentionally the same so the suite does not grow
two half-crawlers, two source registries, or two review queues that disagree.

## BLUF

- **Implemented now:** deterministic source models, content-hash snapshots,
  adapter fan-out, RegWatch proposals, MicroLearn proposals, public Federal
  Register/eCFR client contracts, approved text upload processing, a local
  JSONL review queue, DB-backed review queue, local schedule/job execution
  receipts, review UI, export packet, CLI commands, API endpoints, and focused
  tests.
- **Not implemented in v0:** paid data feeds, keyed external integrations,
  legal interpretation, auto-published training, automatic rule mutation, or
  source-specific parsers for OSHA/state/EU pages.
- **Operating rule:** source intelligence can propose work; humans approve before
  rules, learner assignments, notifications, or modules change state.

## Shared primitives

| Primitive | Purpose | Used by RegWatch | Used by MicroLearn Radar |
| --- | --- | --- | --- |
| `SourceDefinition` | Registry row for an official, trusted, vendor, internal, or web source. | Agency/body, jurisdiction, topic, source quality. | Topic, source quality, audience/domain hints. |
| `SourceSnapshot` | One fetched or uploaded body at a point in time. | Captures the exact text behind a possible requirement change. | Captures the exact text behind a teachable topic. |
| `content_hash` | Change detector based on normalized source text. | Tells reviewers when a source body changed. | Prevents duplicate module suggestions for unchanged material. |
| `SourceSignal` | Scored, evidence-backed finding from one adapter. | Regulatory-change signal. | Microlearning-opportunity signal. |
| `SourceProposal` | Human-review packet with source URL, hash, evidence chain, and action. | Review an obligation or training impact. | Draft a module only after SME/instructional review. |
| `SourceIntelEngine` | Fans each source snapshot out to configured adapters. | Runs RegWatch side by side with future adapters. | Runs MicroLearn side by side with RegWatch and future adapters. |

## Runtime flow

```text
source registry or approved upload
  → source snapshot with content_hash
  → SourceIntelEngine fan-out
  → RegWatchAdapter and/or MicrolearningAdapter
  → SourceProposal with needs_review
  → human legal/compliance/L&D/SME approval
  → optional rule proposal, impact brief, or draft learning module
```

The same source can create more than one proposal. Example: an official agency
page that says employers must train workers may generate a RegWatch obligation
proposal and a MicroLearn module proposal from the same snapshot hash.

## Adapter boundaries

### RegWatchAdapter

RegWatch is conservative by design:

- requires an official/authoritative regulatory source;
- looks for obligation language such as must, required, final rule, effective,
  covered employers, deadline, or similar terms;
- preserves jurisdiction and topics from the source registry;
- emits `signal_type="regulatory_change"`;
- suggests `review_obligation` only;
- keeps `approval_state="needs_review"`.

### MicrolearningAdapter

MicroLearn Radar looks for teachable material, not legal status:

- requires a credible source authority: official, trusted, or internal;
- looks for training/design language such as guide, scenario, practice,
  checklist, examples, feedback, skill, or research-backed cues;
- emits `signal_type="microlearning_opportunity"`;
- suggests a five-minute draft module outline with objectives and a
  check-for-understanding prompt;
- keeps `approval_state="needs_review"`.

## No-paid runtime slice

The repo now includes a no-paid source-monitoring slice:

- `FederalRegisterClient` for public Federal Register API results;
- `ECFRClient` for public eCFR search results;
- `SourceMonitor` to fan fetched snapshots into RegWatch and MicroLearn adapters;
- `SourceReviewStore` to persist review proposals in local JSONL;
- DB-backed runs/proposals/schedules/job executions for durable local ops;
- `source-intel run-upload` for approved local source text when APIs are blocked;
- CLI commands under `complyos source-intel`.

The live public clients are optional and can be dry-run first. Tests use fake
transports and fixture sources, so CI does not depend on internet access or paid
accounts. See [Source Intelligence API Inventory](./source-intelligence-api-inventory.md).

## CSV/upload fallback

Enterprise gates can block API access, crawling, or browser automation. The
engine is therefore built around `SourceSnapshot` rather than a crawler-specific
object. A snapshot can come from:

- an official API or feed;
- an approved page/PDF fetch;
- a vendor document export;
- an internal policy upload;
- a CSV row or manually approved source excerpt.

That means the product can still work when a client says, “We cannot give your
system network access; here is the export.”

## Production hardening now in place

Source Intelligence now has a production-oriented review spine that does not
depend on external API credentials:

- database tables for source-intelligence runs and proposals;
- database tables for schedules and job executions;
- schema migration ledger: `20260612_source_intel_hardening`;
- tenant-scoped repository methods for saving, listing, and deciding proposals;
- tenant-scoped scheduled run receipts for observability;
- service-layer permissions for `source_intel:read`, `source_intel:run`, and
  `source_intel:decide`;
- FastAPI endpoints:
  - `GET /api/v1/source-intel/proposals`;
  - `GET /api/v1/source-intel/export-packet`;
  - `POST /api/v1/source-intel/proposals/{proposal_id}/decision`;
- dashboard UI:
  - `GET /source-intel/review`;
- CLI DB mode:
  - `complyos source-intel run-fixture --db complyos.db --json`;
  - `complyos source-intel review --db complyos.db --json`;
  - `complyos source-intel schedule-add --db complyos.db --name daily-training-watch --json`;
  - `complyos source-intel run-scheduled --db complyos.db --force --json`;
  - `complyos source-intel export-packet --db complyos.db --output packet.json --json`;
- deployment checks:
  - `complyos deployment-check --json`.

This is separate from external API work. See
[External API Research List](./external-api-research-list.md).

## Audit and evidence rules

Every proposal must carry:

- adapter name;
- source URL;
- source content hash;
- source signal type;
- evidence quote;
- reason list;
- evidence chain: `source_registry → source_snapshot → adapter → human_approval`;
- approval state: `needs_review`.
- schedule/job receipt when generated by a scheduled run.

No v0 adapter is allowed to assign training, notify learners, publish modules,
or change ComplyOS rules directly.

## Current verification

Focused coverage lives in:

- `tests/unit/test_source_intelligence.py`;
- `tests/unit/test_source_clients.py`;
- `tests/unit/test_source_monitor_store.py`;
- `tests/unit/test_source_intel_service.py`;
- `tests/unit/test_cli_source_intel.py`;
- `tests/unit/test_api_v1.py`;
- `tests/unit/test_live_dashboard.py`;
- `tests/unit/test_database.py`;
- `tests/unit/test_release.py`.

It proves:

1. one source snapshot can feed RegWatch and MicroLearn Radar;
2. proposals preserve source hash, source URL, evidence chain, and review state;
3. official obligation language creates a RegWatch proposal;
4. credible teachable material creates a MicroLearn module proposal;
5. unchanged source text keeps the same content hash, changed text does not;
6. DB review queues are tenant-scoped and permissioned;
7. local schedules and job executions are persisted;
8. review packets export proposals, decisions, jobs, and action logs;
9. API, CLI, and dashboard surfaces expose the review flow;
10. migration/deployment checks include the source-intelligence hardening pieces.

## Product maturity language

Use this wording in sales/demo docs:

- **Live primitive:** shared source-intelligence models, engine, deterministic
  RegWatch adapter, deterministic MicroLearn adapter, and tests.
- **Contract/product surface:** RegWatch source registry, alert workflow,
  review states, coverage disclosures, and source contracts.
- **Roadmap:** live crawlers, feed schedulers, source-specific parsers, learning
  authoring UI, and customer-specific approval workflows.

Do not imply autonomous live regulatory monitoring until crawlers, parsers,
jurisdiction coverage, reviewer workflow, and customer-specific operational
evidence exist. The current scheduler is local/fixture-capable production
plumbing, not a promise that every external source is monitored.
