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


class LearningRecordStatus(StrEnum):
    ASSIGNED = "assigned"
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    EXEMPT = "exempt"
    EXPIRED = "expired"


_LEARNING_TO_ENROLLMENT_STATUS: dict[LearningRecordStatus, EnrollmentStatus] = {
    LearningRecordStatus.ASSIGNED: EnrollmentStatus.NOT_STARTED,
    LearningRecordStatus.NOT_STARTED: EnrollmentStatus.NOT_STARTED,
    LearningRecordStatus.IN_PROGRESS: EnrollmentStatus.IN_PROGRESS,
    LearningRecordStatus.COMPLETED: EnrollmentStatus.COMPLETED,
    LearningRecordStatus.OVERDUE: EnrollmentStatus.OVERDUE,
    LearningRecordStatus.EXEMPT: EnrollmentStatus.EXEMPT,
    LearningRecordStatus.EXPIRED: EnrollmentStatus.OVERDUE,
}

_ENROLLMENT_TO_LEARNING_STATUS: dict[EnrollmentStatus, LearningRecordStatus] = {
    EnrollmentStatus.NOT_STARTED: LearningRecordStatus.NOT_STARTED,
    EnrollmentStatus.IN_PROGRESS: LearningRecordStatus.IN_PROGRESS,
    EnrollmentStatus.COMPLETED: LearningRecordStatus.COMPLETED,
    EnrollmentStatus.OVERDUE: LearningRecordStatus.OVERDUE,
    EnrollmentStatus.EXEMPT: LearningRecordStatus.EXEMPT,
}


class LearningRecord(BaseModel):
    """Normalized cross-LMS record of a learner's relationship to a learning item."""

    id: str
    user_id: str
    course_id: str
    source_system: str
    source_record_id: str | None = None
    status: LearningRecordStatus = LearningRecordStatus.ASSIGNED
    assigned_date: datetime | None = None
    due_date: date | None = None
    completed_date: datetime | None = None
    completion_percentage: float = 0.0
    score: float | None = None
    exempt: bool = False
    expires_at: date | None = None
    raw_source_hash: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)

    def is_expired(self, as_of: date | None = None) -> bool:
        """Return whether this record's completion has expired as of a date."""
        if self.exempt or self.expires_at is None:
            return False
        return self.expires_at < (as_of or date.today())

    @property
    def is_compliant(self) -> bool:
        return self.exempt or (
            not self.is_expired()
            and self.status in {
                LearningRecordStatus.COMPLETED,
                LearningRecordStatus.EXEMPT,
            }
        )

    @classmethod
    def from_enrollment(
        cls,
        enrollment: Enrollment,
        *,
        source_system: str = "legacy",
        source_record_id: str | None = None,
        raw_source_hash: str | None = None,
    ) -> LearningRecord:
        return cls(
            id=enrollment.id,
            user_id=enrollment.user_id,
            course_id=enrollment.course_id,
            source_system=source_system,
            source_record_id=source_record_id,
            status=_ENROLLMENT_TO_LEARNING_STATUS[enrollment.status],
            assigned_date=enrollment.assigned_date,
            due_date=enrollment.due_date,
            completed_date=enrollment.completed_date,
            completion_percentage=enrollment.completion_percentage,
            score=enrollment.score,
            exempt=enrollment.status == EnrollmentStatus.EXEMPT,
            raw_source_hash=raw_source_hash,
        )

    def to_enrollment(self, as_of: date | None = None) -> Enrollment:
        status = _LEARNING_TO_ENROLLMENT_STATUS[self.status]
        if self.is_expired(as_of):
            status = EnrollmentStatus.OVERDUE
        return Enrollment(
            id=self.id,
            user_id=self.user_id,
            course_id=self.course_id,
            status=status,
            assigned_date=self.assigned_date,
            due_date=self.due_date,
            completed_date=self.completed_date,
            completion_percentage=self.completion_percentage,
            score=self.score,
        )


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


class RemediationAction(BaseModel):
    action_type: str  # reminder, enroll, escalate, notify_manager
    user_id: str
    course_id: str
    triggered_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    status: str = "pending"  # pending, sent, failed
    error_message: str | None = None


class EvidenceLedgerEntry(BaseModel):
    timestamp: datetime
    query_type: str
    query_params: dict[str, Any]
    raw_data_hash: str
    transformation_steps: list[str]
    output_hash: str
    output_summary: str


# ---------------------------------------------------------------------------
# Workflow vocabularies
#
# These name the valid states/types for the import, privacy, and legal-hold
# workflows. They previously lived as ad-hoc string sets scattered across the
# services (one set was even decorative and had drifted from the states the
# code actually wrote), so the type system could not catch a typo'd status or
# an unknown scope. Keeping them here as enums is the single source of truth.
# ---------------------------------------------------------------------------
class ImportBatchStatus(StrEnum):
    # The full plan §6.1 batch lifecycle vocabulary. The states ImportService
    # currently drives are QUARANTINED (preview lands here), PROMOTED, and
    # PROMOTION_FAILED. DRAFT/PREVIEWED/PROMOTION_PENDING/REJECTED/EXPIRED are
    # reserved transitions (e.g. a future async promotion queue or batch TTL);
    # they are kept here as the single source of truth so a later stage adds the
    # transition, not the vocabulary.
    DRAFT = "DRAFT"
    PREVIEWED = "PREVIEWED"
    QUARANTINED = "QUARANTINED"
    PROMOTION_PENDING = "PROMOTION_PENDING"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    PROMOTION_FAILED = "PROMOTION_FAILED"


class ImportRowStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    REJECTED = "REJECTED"
    NEEDS_DECISION = "NEEDS_DECISION"
    PROMOTED = "PROMOTED"
    IGNORED = "IGNORED"


class PrivacyRequestType(StrEnum):
    ACCESS = "access"
    EXPORT = "export"
    CORRECTION = "correction"
    DELETION = "deletion"
    RESTRICTION = "restriction"
    OBJECTION = "objection"


class LegalHoldScope(StrEnum):
    SUBJECT = "subject"
    TENANT = "tenant"
    SYSTEM = "system"


class LegalHoldStatus(StrEnum):
    """Lifecycle states for a legal hold record.

    The create path lands on ``ACTIVE``; ``RELEASED`` is terminal. The string
    values are persisted and read back from the repository, so changing them
    would be a storage migration.
    """

    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RetentionPolicy(BaseModel):
    """Typed retention-policy envelope.

    Five named dataset windows — the same shape the privacy program writes
    through ``configure_retention_policy``. Days are non-negative; unknown
    keys are rejected so a typo'd dataset name is caught at the boundary
    instead of silently never expiring anything.
    """

    privacy_request_days: int = 365
    raw_import_days: int = 30
    ai_proposal_days: int = 180
    evidence_days: int = 2555
    action_log_days: int = 2555

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> RetentionPolicy:
        """Coerce a stored ``{name: days}`` mapping into the typed model.

        Unknown keys are dropped (a stored policy from an older schema still
        loads), but missing keys take the documented default so the cleanup
        path always sees a complete window.
        """
        if not values:
            return cls()
        known = {
            field: int(values[field])
            for field in cls.model_fields
            if field in values
        }
        return cls(**known)

    def as_mapping(self) -> dict[str, int]:
        return {field: int(getattr(self, field)) for field in type(self).model_fields}

    def window_for(self, dataset: str) -> int:
        """Return the retention window in days for the given dataset name."""
        try:
            return int(getattr(self, dataset))
        except AttributeError as exc:
            raise KeyError(f"unknown retention dataset: {dataset!r}") from exc


class PrivacyRequest(BaseModel):
    """A tenant-scoped data-subject / privacy request case.

    The controller-approval gate that authorizes export/deletion of a person's
    data is exposed as a typed predicate (`is_controller_approved`) rather than
    re-derived from nested dict lookups at each call site, so the authorization
    decision has one home the type system can see.
    """

    id: str
    tenant_id: str
    subject_id: str
    request_type: PrivacyRequestType
    status: str
    opened_by: str
    region: str | None = None
    closed_by: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # result_summary is intentionally free-form: it accumulates controller
    # approval, deletion counts, and legal-hold block lists over the case life.
    result_summary: dict[str, Any] = Field(default_factory=dict)

    @property
    def controller_approval(self) -> dict[str, Any]:
        approval = self.result_summary.get("controller_approval")
        return approval if isinstance(approval, dict) else {}

    def is_controller_approved(self) -> bool:
        """True only when a controller has recorded an explicit approval."""
        return self.controller_approval.get("status") == "approved"
