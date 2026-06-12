# RegWatch data contracts

These contracts define the shape of RegWatch data before runtime
implementation. They are intentionally conservative: all AI or parser output is
draft/proposal-only until a human approves an action.

## `RegWatchSource`

Registry entry for an official or authoritative source.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `source_id` | string | yes | Stable slug, e.g. `us-federal-federal-register-api`. |
| `source_name` | string | yes | Human-readable name. |
| `jurisdiction` | string | yes | `US`, `US-CA`, `EU`, etc. |
| `jurisdiction_level` | enum | yes | `federal`, `state`, `regional`, `global`, `local`. |
| `agency_or_body` | string | yes | Publishing agency/body. |
| `source_type` | enum | yes | `api`, `web_page`, `rss`, `pdf`, `bulk_data`, `manual`. |
| `primary_url` | URL | yes | Browser-readable source. |
| `api_or_feed_url` | URL/null | yes | Required key; value may be `null` when no API/feed endpoint is available. |
| `access_model` | enum | yes | `public`, `api_key`, `registered`, `manual_review`, `blocked_or_challenged`. |
| `parser_status` | enum | yes | `not_started`, `candidate`, `stubbed`, `implemented`, `blocked`, `retired`. |
| `domain_tags` | string[] | yes | Example: `safety-training`, `privacy`, `employment`, `education`. |
| `last_verified_at` | datetime | yes | When the source metadata was checked. |
| `coverage_notes` | string | yes | What this source can cover. |
| `known_gaps` | string[] | yes | Missing jurisdictions, rate limits, auth limits, parser gaps. |
| `human_owner_role` | string | yes | Reviewer accountable for this source. |
| `allowed_outputs` | string[] | yes | `alert_proposal`, `training_impact_brief`, `rule_change_proposal`, etc. |

## `RegWatchSourceItem`

Normalized item found during a source check.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `item_id` | string | yes | Stable source-item id. |
| `source_id` | string | yes | Links to `RegWatchSource`. |
| `source_url` | URL | yes | Direct item/source URL when available. |
| `citation_or_identifier` | string | yes | FR citation, CFR section, docket id, CELEX id, OSHA page id, etc. |
| `title` | string | yes | Source title. |
| `summary` | string | yes | Neutral source summary. |
| `publication_date` | date/null | no | When available. |
| `effective_date` | date/null | no | When available. |
| `proposed_date` | date/null | no | When available. |
| `jurisdiction` | string | yes | Copied from source or parsed item. |
| `domain_tags` | string[] | yes | Tags used for relevance. |
| `raw_snapshot_hash` | string/null | no | Optional hash of stored raw/source snapshot. |
| `checked_at` | datetime | yes | Collection timestamp. |
| `coverage_gaps` | string[] | yes | Any parser/source limitations. |

## `RegWatchAlertProposal`

Proposal generated from one or more source items.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `proposal_id` | string | yes | Stable proposal id. |
| `source_item_ids` | string[] | yes | One or more source items. |
| `watch_profile_id` | string | yes | Client/domain watch profile. |
| `relevance_rationale` | string | yes | Why this may matter to the profile. |
| `confidence` | enum | yes | `low`, `medium`, `high`; never “certain.” |
| `training_impact_summary` | string | yes | Draft impact on audiences, roles, courses, or evidence. |
| `suggested_actions` | object[] | yes | Draft actions such as brief, rule proposal, MicroLearn candidate. |
| `human_review_status` | enum | yes | One of the approval states in `docs/regwatch-v0.md`. |
| `reviewer_role` | string/null | no | Legal/compliance/L&D owner. |
| `review_notes` | string/null | no | Human notes. |
| `coverage_disclosure` | string | yes | Plain-language coverage gaps. |
| `created_at` | datetime | yes | Proposal creation time. |
| `expires_or_review_by` | datetime/null | no | Optional review deadline. |

## `RegWatchWatchProfile`

Client-specific watch configuration.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `watch_profile_id` | string | yes | Stable profile id. |
| `tenant_id` | string | yes | Tenant boundary. |
| `jurisdictions` | string[] | yes | Examples: `US`, `US-CA`, `EU`. |
| `domain_tags` | string[] | yes | Safety, privacy, employment, education, accessibility, etc. |
| `audiences` | string[] | yes | Employees, managers, contractors, students, facilitators, etc. |
| `source_ids` | string[] | yes | Allowed registry sources. |
| `excluded_sources` | string[] | no | Sources intentionally out of scope. |
| `human_owner_role` | string | yes | Accountable reviewer. |
| `approval_required_for` | string[] | yes | Rule mutation, training assignment, notifications, publication. |

## Contract invariants

- An alert proposal must include at least one source item.
- A source item must include source URL or source citation plus coverage gaps.
- `confidence` cannot be used as approval.
- `human_review_status` must be explicit and auditable.
- No RegWatch proposal can mutate ComplyOS requirements/rules directly; stated
  bluntly, RegWatch proposals **cannot mutate** production requirements,
  training assignments, learner notifications, or evidence state.
- A downstream ComplyOS rule-change proposal must reference the approved
  RegWatch proposal and still follow normal ComplyOS approval rules.
- Every customer-facing output must include coverage disclosure.

## Minimal example

```json
{
  "proposal_id": "regwatch-proposal-2026-osha-heat-001",
  "source_item_ids": ["source-item-osha-laws-regs-heat-001"],
  "watch_profile_id": "profile-workforce-safety-us",
  "relevance_rationale": "The source is tagged safety-training and may affect field employee onboarding or annual refreshers.",
  "confidence": "medium",
  "training_impact_summary": "Draft only: review whether heat illness prevention content, facilitator notes, and completion evidence need updates.",
  "suggested_actions": [
    {
      "type": "training_impact_brief",
      "status": "draft"
    },
    {
      "type": "complyos_rule_change_proposal",
      "status": "requires_human_approval"
    }
  ],
  "human_review_status": "triage_needed",
  "reviewer_role": "Legal/compliance owner",
  "review_notes": null,
  "coverage_disclosure": "OSHA page source configured; state-level requirements and accountable interpretation require human review.",
  "created_at": "2026-06-12T00:00:00Z",
  "expires_or_review_by": "2026-06-26T00:00:00Z"
}
```
