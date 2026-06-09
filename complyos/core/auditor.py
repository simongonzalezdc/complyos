"""Compliance gap auditing engine."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.models.domain import (
    AssignmentRule,
    AuditReport,
    ComplianceGap,
    Course,
    EnrollmentStatus,
    EvidenceLedgerEntry,
    User,
)


class ComplianceAuditor:
    """Audits compliance gaps across an LMS."""

    def __init__(self, connector: LMSConnector):
        self.connector = connector

    async def audit_gaps(
        self,
        rules: list[AssignmentRule] | None = None,
        department: str | None = None,
        region: str | None = None,
    ) -> tuple[list[ComplianceGap], EvidenceLedgerEntry]:
        """Find users who are missing required training.

        Returns a list of compliance gaps and an evidence ledger entry
        documenting how the result was derived.
        """
        # 1. Build user filters from params + rule target criteria
        user_filters: dict[str, Any] = {"employment_status": "active"}
        if department:
            user_filters["department"] = department
        if region:
            user_filters["region"] = region

        # 2. Fetch mandatory courses (default if no rules provided)
        if rules:
            course_ids = list({cid for rule in rules for cid in rule.course_ids})
            courses = await self.connector.get_courses()
            course_map = {c.id: c for c in courses if c.id in course_ids}
            # Merge rule target criteria into user filters
            for rule in rules:
                for key, value in rule.target_criteria.items():
                    if key not in user_filters:
                        user_filters[key] = value
        else:
            courses = await self.connector.get_courses(filters={"mandatory": True})
            course_map = {c.id: c for c in courses}
            rules = [
                AssignmentRule(
                    name="Mandatory Compliance Training",
                    course_ids=list(course_map.keys()),
                    target_criteria=user_filters,
                )
            ]

        users = await self.connector.get_users(filters=user_filters)
        user_ids = [u.id for u in users]

        # 3. Fetch enrollments for these users and courses
        enrollments = await self.connector.get_enrollments(
            user_ids=user_ids, course_ids=list(course_map.keys())
        )

        # 4. Build lookup: (user_id, course_id) -> enrollment
        enrollment_map: dict[tuple[str, str], Any] = {}
        for e in enrollments:
            enrollment_map[(e.user_id, e.course_id)] = e

        # 5. Find gaps
        gaps: list[ComplianceGap] = []
        for user in users:
            for rule in rules:
                missing: list[Course] = []
                for course_id in rule.course_ids:
                    if course_id not in course_map:
                        continue
                    enrollment = enrollment_map.get((user.id, course_id))
                    if enrollment is None or enrollment.status not in {
                        EnrollmentStatus.COMPLETED,
                        EnrollmentStatus.EXEMPT,
                    }:
                        missing.append(course_map[course_id])

                if missing:
                    days_overdue = None
                    for course in missing:
                        key = (user.id, course.id)
                        if key in enrollment_map and enrollment_map[key].due_date:
                            if enrollment_map[key].due_date < date.today():
                                days_overdue = (date.today() - enrollment_map[key].due_date).days

                    severity = self._calculate_severity(missing, days_overdue)
                    gaps.append(
                        ComplianceGap(
                            user=user,
                            missing_courses=missing,
                            rule_name=rule.name,
                            days_overdue=days_overdue,
                            severity=severity,
                        )
                    )

        # 6. Generate evidence ledger
        ledger = self._create_ledger(
            query_type="audit_gaps",
            query_params={
                "department": department,
                "region": region,
                "rule_count": len(rules),
                "user_count": len(users),
            },
            raw_data={
                "users": [u.model_dump() for u in users],
                "courses": [c.model_dump() for c in course_map.values()],
                "enrollments": [e.model_dump() for e in enrollments],
            },
            output=gaps,
        )

        return gaps, ledger

    async def get_user_status(self, user_id: str) -> dict[str, Any]:
        """Get complete compliance status for a single user."""
        users = await self.connector.get_users()
        user = next((u for u in users if u.id == user_id), None)
        if not user:
            return {"error": f"User {user_id} not found"}

        courses = await self.connector.get_courses(filters={"mandatory": True})
        enrollments = await self.connector.get_enrollments(
            user_ids=[user_id], course_ids=[c.id for c in courses]
        )

        course_status = []
        for course in courses:
            enrollment = next((e for e in enrollments if e.course_id == course.id), None)
            course_status.append(
                {
                    "course": course.model_dump(),
                    "enrollment": enrollment.model_dump() if enrollment else None,
                    "compliant": enrollment is not None
                    and enrollment.status in {EnrollmentStatus.COMPLETED, EnrollmentStatus.EXEMPT},
                }
            )

        compliant_count = sum(1 for cs in course_status if cs["compliant"])
        total_count = len(course_status)

        return {
            "user": user.model_dump(),
            "courses": course_status,
            "summary": {
                "total_mandatory": total_count,
                "completed": compliant_count,
                "missing": total_count - compliant_count,
                "compliance_rate": round(compliant_count / total_count, 2) if total_count > 0 else 0,
            },
        }

    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        """Generate a structured audit report."""
        gaps, ledger = await self.audit_gaps(department=department, region=region)

        gaps_by_severity: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        gaps_by_department: dict[str, int] = {}
        course_missing_counts: dict[str, int] = {}

        for gap in gaps:
            gaps_by_severity[gap.severity] = gaps_by_severity.get(gap.severity, 0) + 1
            dept = gap.user.department
            gaps_by_department[dept] = gaps_by_department.get(dept, 0) + 1
            for course in gap.missing_courses:
                course_missing_counts[course.title] = course_missing_counts.get(course.title, 0) + 1

        top_missing = sorted(course_missing_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return AuditReport(
            generated_at=datetime.now(),
            scope=f"department={department}, region={region}" if (department or region) else "all",
            total_users_audited=len({g.user.id for g in gaps}),
            gaps_found=len(gaps),
            gaps_by_severity=gaps_by_severity,
            gaps_by_department=gaps_by_department,
            top_missing_courses=top_missing,
            evidence_hash=ledger.output_hash,
            details=gaps,
        )

    def _calculate_severity(self, missing_courses: list[Course], days_overdue: int | None) -> str:
        """Calculate gap severity based on missing courses and overdue days."""
        has_mandatory = any(c.mandatory for c in missing_courses)

        if not has_mandatory:
            return "low"

        if days_overdue is None:
            return "medium"

        if days_overdue > 60:
            return "critical"
        elif days_overdue > 30:
            return "high"
        elif days_overdue > 7:
            return "medium"
        else:
            return "low"

    def _create_ledger(
        self,
        query_type: str,
        query_params: dict[str, Any],
        raw_data: dict[str, Any],
        output: list[ComplianceGap],
    ) -> EvidenceLedgerEntry:
        """Create an immutable evidence ledger entry."""
        raw_json = json.dumps(raw_data, sort_keys=True, default=str)
        raw_hash = hashlib.sha256(raw_json.encode()).hexdigest()

        output_json = json.dumps([g.model_dump() for g in output], sort_keys=True, default=str)
        output_hash = hashlib.sha256(output_json.encode()).hexdigest()

        return EvidenceLedgerEntry(
            timestamp=datetime.now(),
            query_type=query_type,
            query_params=query_params,
            raw_data_hash=raw_hash,
            transformation_steps=[
                "fetch_active_users",
                "fetch_mandatory_courses",
                "fetch_enrollments",
                "cross_reference_user_course_enrollment",
                "calculate_severity",
            ],
            output_hash=output_hash,
            output_summary=f"Found {len(output)} compliance gaps across {len({g.user.id for g in output})} users",
        )
