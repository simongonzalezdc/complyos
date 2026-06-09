"""Pydantic domain models for ComplyOS."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EmploymentStatus(StrEnum):
    ACTIVE = "active"
    TERMINATED = "terminated"
    ON_LEAVE = "on_leave"
    CONTRACTOR = "contractor"


class User(BaseModel):
    id: str
    employee_id: str
    email: str
    first_name: str
    last_name: str
    department: str
    region: str
    hire_date: date
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    manager_id: str | None = None
    job_title: str | None = None
    custom_attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Course(BaseModel):
    id: str
    code: str
    title: str
    description: str | None = None
    duration_minutes: int | None = None
    mandatory: bool = False
    category: str | None = None


class EnrollmentStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    EXEMPT = "exempt"


class Enrollment(BaseModel):
    id: str
    user_id: str
    course_id: str
    status: EnrollmentStatus
    assigned_date: datetime | None = None
    due_date: date | None = None
    completed_date: datetime | None = None
    completion_percentage: float = 0.0
    score: float | None = None


class AssignmentRule(BaseModel):
    name: str
    description: str | None = None
    target_criteria: dict[str, Any] = Field(default_factory=dict)
    course_ids: list[str] = Field(default_factory=list)
    deadline_days_from_trigger: int = 30
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    active: bool = True


class ComplianceGap(BaseModel):
    user: User
    missing_courses: list[Course]
    rule_name: str | None = None
    days_overdue: int | None = None
    severity: str = "medium"  # low, medium, high, critical


class AuditReport(BaseModel):
    generated_at: datetime
    scope: str
    total_users_audited: int
    gaps_found: int
    gaps_by_severity: dict[str, int]
    gaps_by_department: dict[str, int]
    top_missing_courses: list[tuple[str, int]]
    evidence_hash: str
    details: list[ComplianceGap] = Field(default_factory=list)


class EvidenceLedgerEntry(BaseModel):
    timestamp: datetime
    query_type: str
    query_params: dict[str, Any]
    raw_data_hash: str
    transformation_steps: list[str]
    output_hash: str
    output_summary: str
