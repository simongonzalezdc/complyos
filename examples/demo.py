#!/usr/bin/env python3
"""Demo script showing the full ComplyOS workflow."""

from __future__ import annotations

import asyncio

from complyos.api.mcp_server import (
    _get_connector,
    audit_compliance_gaps,
    check_connector_health,
    generate_audit_report,
    remediate_compliance_gaps,
    validate_assignment_rule,
)
from complyos.core.repository import LocalRepository


async def main():
    print("=" * 60)
    print("ComplyOS Demo")
    print("=" * 60)

    # 1. Check connector health
    print("\n1. Checking connector health...")
    health = await check_connector_health()
    print(f"   Connector: {health['connector']}")
    print(f"   Status: {health['status']}")

    # 1b. Sync data to local SQLite for rules engine
    print("\n1b. Syncing LMS data to local SQLite...")
    connector = _get_connector()
    repo = LocalRepository()
    users = await connector.get_users()
    courses = await connector.get_courses()
    enrollments = await connector.get_enrollments()
    repo.clear_all()
    repo.sync_users(users)
    repo.sync_courses(courses)
    repo.sync_enrollments(enrollments)
    print(f"   Synced {len(users)} users, {len(courses)} courses, {len(enrollments)} enrollments")

    # 2. Run compliance audit
    print("\n2. Running compliance audit...")
    audit = await audit_compliance_gaps()
    print(f"   Gaps found: {audit['gaps_found']}")
    print(f"   Users affected: {audit['users_affected']}")
    print(f"   Evidence hash: {audit['evidence_hash'][:16]}...")

    # 3. Generate structured report
    print("\n3. Generating audit report...")
    report = await generate_audit_report()
    print(f"   Scope: {report['scope']}")
    print(f"   Gaps by severity: {report['gaps_by_severity']}")

    # 4. Validate an assignment rule
    print("\n4. Validating assignment rule...")
    validation = await validate_assignment_rule(
        name="Engineering Security",
        target_criteria={"department": "Engineering"},
        course_ids=["c1"],
        deadline_days=30,
    )
    print(f"   Valid: {validation['valid']}")
    if validation["issues"]:
        print(f"   Issues: {validation['issues']}")
    print(f"   Would affect: {len(validation['preview']['users'])} users")

    # 5. Remediate gaps
    print("\n5. Remediating gaps...")
    remediation = await remediate_compliance_gaps(auto_remind=True)
    print(f"   Gaps found: {remediation['gaps_found']}")
    print(f"   Actions taken: {remediation['actions_taken']}")
    for action in remediation["actions"]:
        print(f"   - {action['type']} -> {action['user_id']} ({action['status']})")

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
