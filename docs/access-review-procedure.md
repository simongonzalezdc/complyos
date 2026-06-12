# ComplyOS access review procedure

Status: readiness artifact, not completed production evidence.
Owner: security/IT + engineering manager.
Review cadence: quarterly and after material role or system changes.

## Purpose

This Access review procedure defines the evidence ComplyOS needs for enterprise security review around SSO, MFA, privileged access, and employee lifecycle controls.

## Scope

Covered access:

- production application administration;
- database/storage administration;
- repository and CI access;
- Forgejo/project administration;
- MCP/API service-account access;
- support/operator accounts;
- vendor consoles once production vendors are approved.

## SSO and MFA baseline

Before production enterprise use:

1. require SSO for workforce access where the hosting/deployment model supports it;
2. require MFA for administrators and production operators;
3. disable shared human accounts;
4. keep break-glass accounts documented, owner-approved, and periodically tested;
5. export IdP policy screenshots or equivalent configuration evidence.

## Joiner / mover / leaver workflow

### Joiner

- access request ticket;
- manager/system-owner approval;
- role assigned by least privilege;
- production access separated from local/dev access.

### Mover

- review access when job function changes;
- remove stale groups, service roles, and admin grants;
- record reviewer and effective date.

### Leaver

- disable user at identity provider;
- remove repository, infrastructure, vendor, and MCP/service access;
- rotate credentials when shared/legacy access may have been exposed;
- record completion evidence.

## Quarterly review packet

Each quarter, collect:

- user export by system;
- admin/service-account export;
- reviewer;
- review date;
- removals/changes;
- exceptions and owner approval;
- evidence location.

## Evidence checklist

- SSO configuration evidence;
- MFA configuration evidence;
- current access export;
- access-review signoff;
- joiner/mover/leaver sample tickets;
- break-glass account review;
- service-account owner list.

## Remaining external work

- connect production identity provider;
- define customer-hosted vs managed-hosting responsibility split;
- collect first quarterly access-review evidence;
- attach evidence to security packet.
