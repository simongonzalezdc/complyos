# ComplyOS agent surface map

Status: enterprise-hardening branch. This is an operator map, not a marketing page.

## Rule zero

Agents must use the same service-backed workflows as humans. No mutating capability is MCP-only.
Every surface (CLI, MCP, API v1, web shell) calls the same application services, enforces the same
`require_permission(context, PERM_*)` choke-points, and produces the same structured audit trail.

## AI is proposal-only

The AI proposal layer can suggest mappings, anomaly summaries, gap explanations, remediation-message
drafts, and duplicate clustering. It cannot mark a learner compliant, promote imports, execute
remediation, or change rules. PII is redacted before it enters any hash or stored output.
Proposals have a reject + expiry-TTL lifecycle and full provenance hashes. All AI-generated
outputs require explicit human (controller) approval before any downstream action.

## Surface overview

Four surfaces share the same services and permission model. Surface-level access controls differ; the
service boundary is the single authorization choke-point.

| Surface | Entry point | Auth model |
|---|---|---|
| CLI (Typer) | `complyos <command>` | Local-admin actor context (owner role by default) |
| MCP (FastMCP) | stdio/transport tool calls | `agent_service_account` (proposal-only) by default; raise via `COMPLYOS_MCP_ROLE` |
| API v1 (FastAPI) | `http://host/api/v1/*` | Bearer token (`COMPLYOS_API_TOKEN`); fail-closed when unset; `COMPLYOS_ALLOW_INSECURE_LOCAL` for trusted local-only use |
| Web shell | `http://host/shell` | Signed HttpOnly SameSite=Lax session cookie; login exchanges API token (or chosen role in `COMPLYOS_ALLOW_INSECURE_LOCAL` mode) for a signed cookie |

## MCP role model

The default MCP role is `agent_service_account`. This role is proposal-only: it can audit, preview,
and propose, but NOT delete subjects, approve controller decisions, promote imports, auto-remediate,
export PII reports, or send external notifications. Operators raise this explicitly with
`COMPLYOS_MCP_ROLE=<role>` when an MCP service account genuinely needs more. Unknown role values
fail closed at context construction time.

## Web shell at /shell

An authenticated enterprise web shell served by `complyos serve-dashboard` (shell at
`http://host:port/shell`). All nine modules render from live service data — not mock theater.

| Module | URL | What it shows |
|---|---|---|
| Overview | `/shell` or `/shell/overview` | Gap summary tiles, readiness posture, pending source-intel signals |
| Gaps | `/shell/gaps` | Live compliance gap queue from AuditService; filterable by severity |
| Imports | `/shell/imports` | CSV preview/decide/promote wired to ImportService; full import lifecycle |
| Evidence | `/shell/evidence` | Evidence ledger entries from EvidenceService |
| Remediation | `/shell/remediation` | Dry-run remediation proposal (non-mutating GET; execute is an explicit operator action) |
| Source intelligence | `/shell/source-intel` | Regulatory source-signal review queue from SourceIntelService |
| Privacy & retention | `/shell/privacy` | Active legal holds, retention policy posture (read-only GET; mutations via CLI/API) |
| Readiness | `/shell/readiness` | Control readiness matrix, posture, tenant metadata |
| Administration | `/shell/admin` | Tenant-scoped role-binding list from RoleAdminService |

Import preview/decide/promote are fully wired: `POST /shell/imports/preview`, `POST /shell/imports/{batch_id}/decisions`, `POST /shell/imports/{batch_id}/promote`.

WCAG 2.2 AA accessibility and color-contrast are enforced by tests. Roles lacking a module's permission see a clear inline panel naming the missing permission rather than a torn-down page.

## Surface matrix

| Job | Preferred surface | Command / tool / endpoint | Permission | Guardrail |
|---|---|---|---|---|
| Check readiness | CLI, MCP, API, or shell | `complyos readiness --json`; `check_readiness`; `GET /api/v1/readiness`; `/shell/readiness` | `readiness:read` | Readiness/control-mapping language only. No legal or certification claims. |
| Audit compliance gaps | CLI, MCP, API, or shell | `complyos audit --json`; `audit_compliance_gaps`; `GET /api/v1/audits`; `/shell/gaps` | `audit:run` | Use deterministic audit output and evidence hash. |
| Generate audit report | CLI, MCP, or API | `complyos report --json`; `generate_audit_report`; `GET /api/v1/report` | `audit:run` | Same evidence hash as audit. |
| Compliance digest (what changed) | CLI, MCP, or API | `complyos digest --json`; `generate_compliance_digest`; `GET /api/v1/digest` | `audit:run` | Diffs against last snapshot for the same scope. |
| User/learner status | CLI, MCP, or API | `complyos status <user_id> --json`; `get_user_compliance_status`; `GET /api/v1/learners/{user_id}/status` | `audit:run` | Tenant-scoped. |
| Preview CSV import | CLI, MCP, API, or shell | `complyos import preview file.csv --json`; `preview_import_batch`; `POST /api/v1/imports/preview`; `/shell/imports` | `import:preview` | Does not mutate active records. Review all issues before deciding. |
| Record import row decision | CLI, MCP, API, or shell | `complyos import decide <batch> <row> --decision <type>`; `decide_import_row`; `POST /api/v1/imports/{batch_id}/decisions`; `/shell/imports/{batch_id}/decisions` | `import:decide` | Decisions: accept, reject, map_field, merge_duplicate, ignore_row, require_manual_review. |
| Promote import | CLI, MCP, API, or shell | `complyos import promote <batch> --json`; `promote_import_batch`; `POST /api/v1/imports/{batch_id}/promote`; `/shell/imports/{batch_id}/promote` | `import:promote` | Blocked unless every row is valid, accepted, or ignored. Evidence log required. |
| Read evidence | CLI, MCP, API, or shell | `complyos evidence list --tenant <tenant> --json`; `list_evidence_ledger`; `GET /api/v1/evidence`; `/shell/evidence` | `evidence:read` | Tenant-scoped; cite hashes in summaries. |
| Export audit report (file) | CLI or MCP | `complyos export report.html`; `export_audit_report_html` | `evidence:export` | MCP default role lacks this; raise `COMPLYOS_MCP_ROLE`. |
| Export audit report (API) | API | `POST /api/v1/exports/reports` | `evidence:export` | Returns rendered content in response body; never writes to server disk from a remote call. |
| Generate dashboard (file) | CLI or MCP | `complyos dashboard dashboard.html`; `export_compliance_dashboard` | `evidence:export` | MCP default role lacks this; raise `COMPLYOS_MCP_ROLE`. |
| AI field mapping proposal | CLI, MCP, or API | `complyos ai propose-mapping <headers>`; `propose_field_mapping`; `POST /api/v1/ai/proposals/mapping` | `ai:propose` | Proposal-only. Headers-only default. PII is not stored. |
| Approve AI proposal | CLI, MCP, or API | `complyos ai approve <proposal>`; `approve_ai_proposal`; `POST /api/v1/ai/proposals/{id}/approve` | `ai:approve` | Metadata approval only; does not change compliance truth. |
| Validate assignment rule | CLI, MCP, or API | `complyos validate-rule rule.json`; `validate_assignment_rule`; `POST /api/v1/rules/validate` | `rules:preview` | Checks for unknown courses, empty targets, and affected users. |
| Preview assignment rule | CLI, MCP, or API | `complyos preview-rule rule.json`; `preview_assignment_rule`; `POST /api/v1/rules/preview` | `rules:preview` | Affected users, missing courses, and enrollment count. |
| Remediate gaps | CLI, MCP, or API | `complyos remediate`; `remediate_compliance_gaps`; `POST /api/v1/remediations` | `remediation:execute` | MCP default role lacks this; raise `COMPLYOS_MCP_ROLE`. Write-back is never the default. |
| Sync LMS data | CLI, MCP, or API | `complyos sync`; `sync`; `POST /api/v1/sync` | `audit:run` | Clears and re-populates the local cache. |
| List connectors | CLI, MCP, or API | `complyos connectors`; `list_connectors`; `GET /api/v1/connectors` | `connectors:read` | Capability matrix only; does not connect to or mutate any LMS. |
| Connector health | CLI, MCP, or API | `complyos health`; `check_connector_health`; `GET /api/v1/connectors/health` | `connectors:read` | Do not leak credentials. |
| Collect security evidence | CLI, MCP, or API | `complyos security evidence --json`; `collect_security_evidence`; `GET /api/v1/security/evidence` | `security:evidence:read` | Readiness-only control map; attach real audit artifacts separately. |
| Collect governance packet | CLI, MCP, or API | `complyos governance packet --lane campus --json`; `collect_governance_packet`; `GET /api/v1/governance/packet` | `governance:read` | Readiness-only AI/school/FCRA boundary packet; attach counsel-reviewed terms separately. |
| List source-intel proposals | CLI, MCP, or API | `complyos source-intel review --json`; (list via `SourceIntelService`); `GET /api/v1/source-intel/proposals` | `source_intel:read` | Regulatory source signals; proposals require review before action. |
| Decide source-intel proposal | CLI or API | `complyos source-intel review --proposal-id <id> --state <state>`; `POST /api/v1/source-intel/proposals/{id}/decision` | `source_intel:decide` | States: approved, rejected, deferred. |
| Export source-intel packet | CLI or API | `complyos source-intel export-packet`; `GET /api/v1/source-intel/export-packet` | `source_intel:read` | Review/audit packet for human sign-off. |
| Source-intel scheduled runs | CLI | `complyos source-intel schedule-add / schedule-list / run-scheduled` | `source_intel:run` | Local schedules; fixture and free-public modes. |
| Send notification | MCP | `send_notification` | `notifications:manage` | MCP default role lacks this; raise `COMPLYOS_MCP_ROLE`. Custom external email. |
| List notification outbox | CLI or API | `complyos notifications list`; `GET /api/v1/notifications/preferences` | `notifications:manage` | Pending deliveries without exposing webhook URLs. |
| Set notification preference | CLI or API | `complyos notifications preference-set --channel <ch>`; `PUT /api/v1/notifications/preferences` | `notifications:manage` | Channel/event enable-disable kill switches. |
| Drain notification outbox | CLI | `complyos notifications drain` | `notifications:manage` | Dry-run by default; use `--send` for outbound webhook calls. |
| Receive inbound hook | API | `POST /api/v1/hooks/inbound/{source}` | `notifications:manage` | HMAC-SHA256 signature required unless `COMPLYOS_ALLOW_INSECURE_LOCAL`; `COMPLYOS_INBOUND_WEBHOOK_SECRET` configures the secret. |
| Create privacy request | CLI, MCP, or API | `complyos privacy request <subject>`; `create_privacy_request`; `POST /api/v1/privacy/requests` | `privacy:request` | Case opens as `PENDING_CONTROLLER_APPROVAL`. Tenant-scoped. |
| Approve privacy request | CLI, MCP, or API | `complyos privacy approve <request>`; `approve_privacy_request`; `POST /api/v1/privacy/requests/{id}/approve` | `privacy:approve` | Records controller approval before export/delete. |
| Export privacy subject | CLI, MCP, or API | `complyos privacy export <request>`; `export_privacy_subject`; `POST /api/v1/privacy/requests/{id}/export` | `privacy:export` | Blocked until approval. Do not disclose other subjects. |
| Delete privacy subject | CLI, MCP, or API | `complyos privacy delete <request>`; `delete_privacy_subject`; `POST /api/v1/privacy/requests/{id}/delete` | `privacy:delete` | Blocked until approval and again on active legal hold; logs counts, not raw data. |
| Create legal hold | CLI, MCP, or API | `complyos privacy legal-hold <subject> --reason <r>`; `create_legal_hold`; `POST /api/v1/privacy/legal-holds` | `legal_hold:manage` | Active holds block deletion. Scope: subject, tenant, or system. |
| Release legal hold | CLI, MCP, or API | `complyos privacy release-hold <hold>`; `release_legal_hold`; `POST /api/v1/privacy/legal-holds/{id}/release` | `legal_hold:manage` | Release requires explicit command/call. |
| Configure retention | CLI, MCP, or API | `complyos privacy retention configure ...`; `configure_privacy_retention`; `POST /api/v1/privacy/retention-policy` | `privacy:retention:manage` | Policy fields: raw_import_days, evidence_days, action_log_days, ai_proposal_days, privacy_request_days. |
| Run retention cleanup | CLI, MCP, or API | `complyos privacy retention run --dry-run`; `run_privacy_retention`; `POST /api/v1/privacy/retention-policy/run` | `privacy:retention:manage` | Dry-run by default. Deletes eligible closed privacy cases, terminal raw import rows/decisions, rejected/expired AI proposals, evidence entries, and action logs unless legal hold blocks them. |
| List role bindings | CLI, API, or shell | `complyos admin role-bindings list`; `GET /api/v1/admin/roles`; `/shell/admin` | `admin:manage` | Tenant-scoped bindings. |
| Set role binding | CLI or API | `complyos admin role-bindings set <actor> --role <role>`; `POST /api/v1/admin/roles` | `admin:manage` | Creates or replaces a binding. |
| Remove role binding | CLI or API | `complyos admin role-bindings remove <actor>`; `DELETE /api/v1/admin/roles/{actor_id}` | `admin:manage` | Removes binding; actor falls back to default role permissions. |
| Run scheduled audits | CLI | `complyos run-schedule` | `audit:run` | Runs due scheduled audit jobs; optional notification enqueueing. |
| Run deployment checks | CLI | `complyos deployment-check` | local only | Verifies operator-release artifacts are present. |
| Release check | CLI | `complyos release-check` | local only | Checks whether the repository has operator-release artifacts. |

## MCP tools (full list)

All 30 tools call the same application services as CLI and API. The default `agent_service_account`
role is granted audit, preview, and proposal capabilities only.

**Read-only / proposal-safe (available to default role):**
`audit_compliance_gaps`, `get_user_compliance_status`, `generate_audit_report`,
`generate_compliance_digest`, `sync`, `list_connectors`, `check_connector_health`,
`validate_assignment_rule`, `preview_assignment_rule`, `check_readiness`,
`preview_import_batch`, `list_evidence_ledger`, `propose_field_mapping`,
`collect_security_evidence`, `collect_governance_packet`, `create_privacy_request`.

**Mutating / privileged (require elevated `COMPLYOS_MCP_ROLE`):**
`remediate_compliance_gaps` (`remediation:execute`),
`export_audit_report_html` (`evidence:export`),
`export_compliance_dashboard` (`evidence:export`),
`send_notification` (`notifications:manage`),
`promote_import_batch` (`import:promote`),
`decide_import_row` (`import:decide`),
`approve_ai_proposal` (`ai:approve`),
`approve_privacy_request` (`privacy:approve`),
`export_privacy_subject` (`privacy:export`),
`delete_privacy_subject` (`privacy:delete`),
`create_legal_hold` (`legal_hold:manage`),
`release_legal_hold` (`legal_hold:manage`),
`configure_privacy_retention` (`privacy:retention:manage`),
`run_privacy_retention` (`privacy:retention:manage`).

## Complete API v1 endpoints

**Health and readiness**
- `GET /api/v1/health`
- `GET /api/v1/readiness`

**Audit and reporting**
- `GET /api/v1/audits` (alias: `GET /api/v1/audit`)
- `GET /api/v1/report`
- `GET /api/v1/digest`
- `GET /api/v1/learners/{user_id}/status` (alias: `GET /api/v1/users/{user_id}/status`)
- `POST /api/v1/exports/reports`

**Connectors**
- `GET /api/v1/connectors`
- `GET /api/v1/connectors/health`

**Sync**
- `POST /api/v1/sync`

**Assignment rules**
- `POST /api/v1/rules/validate`
- `POST /api/v1/rules/preview`

**Remediation**
- `POST /api/v1/remediations` (alias: `POST /api/v1/remediate`)

**Imports**
- `POST /api/v1/imports/preview`
- `POST /api/v1/imports/{batch_id}/decisions`
- `POST /api/v1/imports/{batch_id}/promote`

**Evidence**
- `GET /api/v1/evidence`

**AI proposals**
- `POST /api/v1/ai/proposals/mapping`
- `POST /api/v1/ai/proposals/{proposal_id}/approve`

**Security and governance**
- `GET /api/v1/security/evidence`
- `GET /api/v1/governance/packet`

**Source intelligence**
- `GET /api/v1/source-intel/proposals`
- `POST /api/v1/source-intel/proposals/{proposal_id}/decision`
- `GET /api/v1/source-intel/export-packet`

**Notifications**
- `GET /api/v1/notifications/preferences`
- `PUT /api/v1/notifications/preferences`

**Inbound hooks**
- `POST /api/v1/hooks/inbound/{source}`

**Privacy**
- `POST /api/v1/privacy/requests`
- `POST /api/v1/privacy/requests/{request_id}/approve`
- `POST /api/v1/privacy/requests/{request_id}/export`
- `POST /api/v1/privacy/requests/{request_id}/delete`
- `POST /api/v1/privacy/legal-holds`
- `POST /api/v1/privacy/legal-holds/{hold_id}/release`
- `POST /api/v1/privacy/retention-policy`
- `POST /api/v1/privacy/retention-policy/run`

**Admin**
- `GET /api/v1/admin/roles`
- `POST /api/v1/admin/roles`
- `DELETE /api/v1/admin/roles/{actor_id}`

## Agent operating sequence

1. Run readiness first for enterprise/customer-facing work.
2. Preview imports before any promotion. Stop on `REJECTED`, `NEEDS_DECISION`, or `PENDING` rows.
3. Use the web shell (`/shell`) for interactive operator workflows: gap review, import lifecycle,
   evidence inspection, source-intel triage, privacy posture, readiness matrix, and admin.
4. If using AI mapping, keep it proposal-only and store provenance. Require explicit approval.
5. Cite evidence hashes and batch IDs in user-facing summaries.
6. For privacy requests, create a case first and record controller approval before export/delete.
7. Never delete if a legal hold is active; tenant-level holds also block retention purges.
8. Do not say the product has achieved legal or certification status. Use readiness/control-mapping
   language until reviewed artifacts exist and counsel has confirmed the position.

## Production auth posture

- Local CLI uses explicit local-admin context (owner role by default).
- API v1 is context-backed. Set `COMPLYOS_API_TOKEN` for bearer-token auth. Fail-closed when
  the token is unset and `COMPLYOS_ALLOW_INSECURE_LOCAL` is not set.
- API v1 applies in-process per-identity rate limiting on mutating endpoints when
  `COMPLYOS_RATE_LIMIT_PER_MINUTE` is set; returns structured 429 + `Retry-After`.
- Web shell login exchanges the API token for a signed HttpOnly SameSite=Lax session cookie.
  Set `COMPLYOS_SESSION_SECRET` for the signing key (falls back to `COMPLYOS_API_TOKEN`).
  Mark the cookie Secure with `COMPLYOS_SESSION_SECURE=1` when serving over HTTPS.
- Remote MCP must run as a scoped service account. Do not grant `admin:manage` or
  `remediation:execute` by default. Use `COMPLYOS_MCP_ROLE` to opt up with explicit intent.
- Inbound hooks require HMAC-SHA256 signature verification (`COMPLYOS_INBOUND_WEBHOOK_SECRET`).
  Signature validation is bypassed only when `COMPLYOS_ALLOW_INSECURE_LOCAL` is set.
- Mutating surfaces must go through service-layer permissions; no surface bypasses the
  `require_permission` choke-point.

## Tenant model

Single-tenant runtime by default. Tenant governance metadata (data_region, processing_purpose,
data_categories, retention_policy, subprocessor_profile) is surfaced through the readiness
service. Multi-tenant SaaS is not built — see docs/multi-tenancy.md.
