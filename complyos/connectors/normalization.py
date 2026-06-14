"""Shared LMS-export normalization helpers.

This is the intentionally-public home for the column-aliasing, value-parsing,
and status-mapping logic used to turn raw CSV/LMS rows into the ComplyOS domain
model. It is imported by the CSV connector AND by the application-layer import
and AI-proposal services, so it lives here rather than as private helpers
inside one connector (which made the service layer reach down into a single
connector's internals).
"""

from __future__ import annotations

from datetime import date, datetime

from complyos.models.domain import EnrollmentStatus, LearningRecordStatus

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
DATETIME_FORMATS = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", *DATE_FORMATS]

# Canonical enrollment field -> accepted column-name aliases (lowercased after
# stripping spaces/underscores/dashes). First match wins per row.
ENROLLMENT_ALIASES: dict[str, list[str]] = {
    "id": ["id", "enrollmentid", "registrationid", "learningrecordid", "transcriptid"],
    "user_id": ["userid", "user", "learnerid", "studentid"],
    "course_id": ["courseid", "course", "learningitemid"],
    "status": ["status", "enrollmentstatus", "completionstatus"],
    "assigned_date": ["assigneddate", "enrolldate", "enrollmentdate", "registrationdate"],
    "due_date": ["duedate", "deadline", "targetdate"],
    "completed_date": ["completeddate", "completiondate", "finisheddate"],
    "completion_percentage": ["completionpercentage", "progress", "percentcomplete"],
    "score": ["score", "grade", "finalscore"],
    "expires_at": ["expiresat", "expirationdate", "expirydate", "recertificationdate"],
    "source_system": ["sourcesystem", "system", "platform", "lms"],
    "source_record_id": ["sourcerecordid", "externalid", "transcriptitemid"],
    "exempt": ["exempt", "waived", "exception"],
}

# LMS-specific status vocabulary -> EnrollmentStatus
STATUS_SYNONYMS: dict[str, EnrollmentStatus] = {
    "completed": EnrollmentStatus.COMPLETED,
    "complete": EnrollmentStatus.COMPLETED,
    "passed": EnrollmentStatus.COMPLETED,
    "finished": EnrollmentStatus.COMPLETED,
    "in_progress": EnrollmentStatus.IN_PROGRESS,
    "inprogress": EnrollmentStatus.IN_PROGRESS,
    "started": EnrollmentStatus.IN_PROGRESS,
    "active": EnrollmentStatus.IN_PROGRESS,
    "not_started": EnrollmentStatus.NOT_STARTED,
    "notstarted": EnrollmentStatus.NOT_STARTED,
    "enrolled": EnrollmentStatus.NOT_STARTED,
    "registered": EnrollmentStatus.NOT_STARTED,
    "overdue": EnrollmentStatus.OVERDUE,
    "past_due": EnrollmentStatus.OVERDUE,
    "exempt": EnrollmentStatus.EXEMPT,
    "waived": EnrollmentStatus.EXEMPT,
}


def normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def remap_row(row: dict[str, str], aliases: dict[str, list[str]]) -> dict[str, str]:
    """Map a raw CSV row onto canonical field names via the alias table."""
    normalized = {normalize_header(k): (v or "").strip() for k, v in row.items() if k}
    result: dict[str, str] = {}
    for field, candidates in aliases.items():
        for candidate in candidates:
            if candidate in normalized and normalized[candidate] != "":
                result[field] = normalized[candidate]
                break
    return result


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.rstrip("%"))
    except ValueError:
        return None


def is_expired(expires_at: date | None, as_of: date | None = None) -> bool:
    return expires_at is not None and expires_at < (as_of or date.today())


def normalize_status_for_expiry(
    status: EnrollmentStatus,
    expires_at: date | None,
    *,
    exempt: bool = False,
    as_of: date | None = None,
) -> EnrollmentStatus:
    if exempt or status == EnrollmentStatus.EXEMPT:
        return EnrollmentStatus.EXEMPT
    if status == EnrollmentStatus.COMPLETED and is_expired(expires_at, as_of):
        return EnrollmentStatus.OVERDUE
    return status


def to_learning_status(
    status: EnrollmentStatus,
    expires_at: date | None = None,
    *,
    exempt: bool = False,
    as_of: date | None = None,
) -> LearningRecordStatus:
    status = normalize_status_for_expiry(status, expires_at, exempt=exempt, as_of=as_of)
    return {
        EnrollmentStatus.NOT_STARTED: LearningRecordStatus.NOT_STARTED,
        EnrollmentStatus.IN_PROGRESS: LearningRecordStatus.IN_PROGRESS,
        EnrollmentStatus.COMPLETED: LearningRecordStatus.COMPLETED,
        EnrollmentStatus.OVERDUE: (
            LearningRecordStatus.EXPIRED
            if is_expired(expires_at, as_of) and not exempt
            else LearningRecordStatus.OVERDUE
        ),
        EnrollmentStatus.EXEMPT: LearningRecordStatus.EXEMPT,
    }[status]
