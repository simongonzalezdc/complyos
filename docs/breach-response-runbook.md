# ComplyOS breach response runbook

Status: readiness artifact, not legal advice.
Owner: security/privacy/legal review.
Review cadence: every 6 months and after any incident/tabletop.

## Purpose

This runbook defines the Breach response workflow for suspected unauthorized access, disclosure, loss, alteration, or destruction of ComplyOS customer data.

## Severity levels

| Level | Description | Examples |
|---|---|---|
| SEV-1 | confirmed or highly likely exposure of customer personal data | tenant data exposed, compromised credentials, cross-tenant access |
| SEV-2 | serious security event with potential data impact | suspicious admin activity, vulnerable deployment with exposure window |
| SEV-3 | contained issue with low data impact | blocked attack, local dev secret exposure without production access |
| SEV-4 | informational | failed login spikes, scanner noise |

## Triage

Within the first response window:

1. create incident ID;
2. assign incident commander;
3. preserve evidence;
4. identify affected tenant(s), systems, data categories, and timeframe;
5. determine whether personal data, student data, or regulated workforce data may be involved;
6. engage security, privacy/legal, engineering, and customer owner as needed.

## Containment

Containment actions may include:

- revoke credentials or tokens;
- disable affected integration;
- isolate affected tenant/environment;
- block network path;
- pause imports/exports;
- rotate secrets;
- deploy emergency fix;
- preserve logs before lifecycle deletion.

## Investigation

Collect:

- timeline;
- actor/account IDs;
- tenant IDs;
- request IDs;
- source IP/session metadata if available;
- data classes touched;
- counts of affected records;
- logs and evidence hashes;
- root cause;
- containment and eradication actions.

## Notification assessment

Privacy/legal review determines notification requirements by contract and jurisdiction. The assessment should consider:

- whether personal data was involved;
- whether student data was involved;
- data sensitivity;
- likelihood of harm;
- affected regions;
- customer contract notice windows;
- regulator or individual notice obligations;
- law-enforcement or legal hold concerns.

Do not send customer/regulator notices without approved incident communications.

## Customer communication packet

Prepare:

- incident ID;
- summary of what happened;
- affected services and timeframe;
- affected data categories and approximate counts;
- containment actions;
- customer actions required, if any;
- remediation plan;
- next update time;
- final root-cause report timing.

## Post-incident review

Within 5-10 business days after closure:

- document root cause;
- document what worked/failed;
- create remediation tickets;
- update tests/runbooks/monitoring;
- update risk register;
- run lessons-learned review;
- store final evidence packet.

## Implementation gaps

- Add incident case template.
- Add incident evidence folder structure.
- Add alerting/monitoring integration.
- Add customer notification template.
- Add tabletop schedule and evidence.
