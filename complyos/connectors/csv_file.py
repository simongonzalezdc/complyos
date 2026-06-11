"""CSV file connector for LMS exports.

Reads users.csv, courses.csv, and enrollments.csv from a directory.
Works with exports from any LMS (Canvas, Cornerstone, Moodle, Docebo, ...)
by accepting common column-name aliases. Read-only: reminders are not
supported because a CSV export has no write-back channel.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.models.domain import (
    Course,
    EmploymentStatus,
    Enrollment,
    EnrollmentStatus,
    LearningRecord,
    LearningRecordStatus,
    User,
)

USERS_FILE = "users.csv"
COURSES_FILE = "courses.csv"
ENROLLMENTS_FILE = "enrollments.csv"

# Canonical field -> accepted column-name aliases (lowercased, after
# stripping spaces/underscores/dashes). First match wins per row.
USER_ALIASES: dict[str, list[str]] = {
    "id": ["id", "userid", "user"],
    "employee_id": ["employeeid", "employeenumber", "empid", "staffid"],
    "email": ["email", "emailaddress", "mail"],
    "first_name": ["firstname", "givenname", "first"],
    "last_name": ["lastname", "surname", "familyname", "last"],
    "department": ["department", "dept", "orgunit", "division"],
    "region": ["region", "location", "country"],
    "hire_date": ["hiredate", "startdate", "dateofhire"],
    "employment_status": ["employmentstatus", "status", "employeestatus"],
    "manager_id": ["managerid", "supervisorid", "manager"],
    "job_title": ["jobtitle", "title", "position"],
}

COURSE_ALIASES: dict[str, list[str]] = {
    "id": ["id", "courseid", "course"],
    "code": ["code", "coursecode", "shortname"],
    "title": ["title", "coursetitle", "name", "coursename"],
    "description": ["description", "summary"],
    "duration_minutes": ["durationminutes", "duration", "minutes"],
    "mandatory": ["mandatory", "required", "compliance"],
    "category": ["category", "type", "coursetype"],
}

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

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
DATETIME_FORMATS = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", *DATE_FORMATS]

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

TRUTHY = {"true", "yes", "y", "1", "required", "mandatory"}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _remap_row(row: dict[str, str], aliases: dict[str, list[str]]) -> dict[str, str]:
    """Map a raw CSV row onto canonical field names via the alias table."""
    normalized = {_normalize_header(k): (v or "").strip() for k, v in row.items() if k}
    result: dict[str, str] = {}
    for field, candidates in aliases.items():
        for candidate in candidates:
            if candidate in normalized and normalized[candidate] != "":
                result[field] = normalized[candidate]
                break
    return result


def _parse_date(value: str | None) -> date | None:
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


def _parse_datetime(value: str | None) -> datetime | None:
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


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.rstrip("%"))
    except ValueError:
        return None


def _hash_row(row: dict[str, str]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_learning_status(status: EnrollmentStatus) -> LearningRecordStatus:
    return {
        EnrollmentStatus.NOT_STARTED: LearningRecordStatus.NOT_STARTED,
        EnrollmentStatus.IN_PROGRESS: LearningRecordStatus.IN_PROGRESS,
        EnrollmentStatus.COMPLETED: LearningRecordStatus.COMPLETED,
        EnrollmentStatus.OVERDUE: LearningRecordStatus.OVERDUE,
        EnrollmentStatus.EXEMPT: LearningRecordStatus.EXEMPT,
    }[status]


class CSVConnector(LMSConnector):
    """Connector that reads LMS data from CSV exports in a directory.

    Environment variables:
        COMPLYOS_CSV_DIR: directory containing users.csv, courses.csv,
            enrollments.csv
    """

    name = "csv"

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.getenv("COMPLYOS_CSV_DIR") or ".")
        self._users: list[User] | None = None
        self._courses: list[Course] | None = None
        self._enrollments: list[Enrollment] | None = None
        self._learning_records: list[LearningRecord] | None = None
        self.skipped_rows: dict[str, int] = {USERS_FILE: 0, COURSES_FILE: 0, ENROLLMENTS_FILE: 0}

    async def authenticate(self) -> bool:
        return all(
            (self.data_dir / f).is_file()
            for f in (USERS_FILE, COURSES_FILE, ENROLLMENTS_FILE)
        )

    def _read_rows(self, filename: str) -> list[dict[str, str]]:
        path = self.data_dir / filename
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def _load_users(self) -> list[User]:
        if self._users is None:
            self._users = []
            for row in self._read_rows(USERS_FILE):
                mapped = _remap_row(row, USER_ALIASES)
                hire_date = _parse_date(mapped.get("hire_date"))
                if "id" not in mapped or "email" not in mapped or hire_date is None:
                    self.skipped_rows[USERS_FILE] += 1
                    continue
                raw_status = mapped.get("employment_status", "active").lower()
                try:
                    status = EmploymentStatus(raw_status)
                except ValueError:
                    status = EmploymentStatus.ACTIVE
                self._users.append(
                    User(
                        id=mapped["id"],
                        employee_id=mapped.get("employee_id", mapped["id"]),
                        email=mapped["email"],
                        first_name=mapped.get("first_name", ""),
                        last_name=mapped.get("last_name", ""),
                        department=mapped.get("department", "Unknown"),
                        region=mapped.get("region", "Unknown"),
                        hire_date=hire_date,
                        employment_status=status,
                        manager_id=mapped.get("manager_id"),
                        job_title=mapped.get("job_title"),
                    )
                )
        return self._users

    def _load_courses(self) -> list[Course]:
        if self._courses is None:
            self._courses = []
            for row in self._read_rows(COURSES_FILE):
                mapped = _remap_row(row, COURSE_ALIASES)
                if "id" not in mapped:
                    self.skipped_rows[COURSES_FILE] += 1
                    continue
                duration_raw = _parse_float(mapped.get("duration_minutes"))
                self._courses.append(
                    Course(
                        id=mapped["id"],
                        code=mapped.get("code", mapped["id"]),
                        title=mapped.get("title", mapped.get("code", mapped["id"])),
                        description=mapped.get("description"),
                        duration_minutes=int(duration_raw) if duration_raw else None,
                        mandatory=mapped.get("mandatory", "").lower() in TRUTHY,
                        category=mapped.get("category"),
                    )
                )
        return self._courses

    def _load_enrollments(self) -> list[Enrollment]:
        if self._enrollments is None:
            self._enrollments = []
            for i, row in enumerate(self._read_rows(ENROLLMENTS_FILE)):
                mapped = _remap_row(row, ENROLLMENT_ALIASES)
                if "user_id" not in mapped or "course_id" not in mapped:
                    self.skipped_rows[ENROLLMENTS_FILE] += 1
                    continue
                raw_status = mapped.get("status", "not_started").lower().replace(" ", "_")
                status = STATUS_SYNONYMS.get(raw_status, EnrollmentStatus.NOT_STARTED)
                self._enrollments.append(
                    Enrollment(
                        id=mapped.get("id", f"csv-{i}"),
                        user_id=mapped["user_id"],
                        course_id=mapped["course_id"],
                        status=status,
                        assigned_date=_parse_datetime(mapped.get("assigned_date")),
                        due_date=_parse_date(mapped.get("due_date")),
                        completed_date=_parse_datetime(mapped.get("completed_date")),
                        completion_percentage=_parse_float(mapped.get("completion_percentage"))
                        or 0.0,
                        score=_parse_float(mapped.get("score")),
                    )
                )
        return self._enrollments

    def _load_learning_records(self) -> list[LearningRecord]:
        if self._learning_records is None:
            self._learning_records = []
            for i, row in enumerate(self._read_rows(ENROLLMENTS_FILE)):
                mapped = _remap_row(row, ENROLLMENT_ALIASES)
                if "user_id" not in mapped or "course_id" not in mapped:
                    self.skipped_rows[ENROLLMENTS_FILE] += 1
                    continue
                raw_status = mapped.get("status", "not_started").lower().replace(" ", "_")
                enrollment_status = STATUS_SYNONYMS.get(raw_status, EnrollmentStatus.NOT_STARTED)
                record_id = mapped.get("id", f"csv-{i}")
                source_system = mapped.get("source_system", self.name)
                explicit_exempt = mapped.get("exempt", "").lower() in TRUTHY
                self._learning_records.append(
                    LearningRecord(
                        id=record_id,
                        user_id=mapped["user_id"],
                        course_id=mapped["course_id"],
                        source_system=source_system,
                        source_record_id=mapped.get("source_record_id"),
                        status=_to_learning_status(enrollment_status),
                        assigned_date=_parse_datetime(mapped.get("assigned_date")),
                        due_date=_parse_date(mapped.get("due_date")),
                        completed_date=_parse_datetime(mapped.get("completed_date")),
                        completion_percentage=_parse_float(mapped.get("completion_percentage"))
                        or 0.0,
                        score=_parse_float(mapped.get("score")),
                        exempt=explicit_exempt or enrollment_status == EnrollmentStatus.EXEMPT,
                        expires_at=_parse_date(mapped.get("expires_at")),
                        raw_source_hash=_hash_row(row),
                        source_payload=dict(row),
                    )
                )
        return self._learning_records

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        result = self._load_users()
        if filters:
            if "department" in filters:
                result = [u for u in result if u.department == filters["department"]]
            if "region" in filters:
                result = [u for u in result if u.region == filters["region"]]
            if "employment_status" in filters:
                result = [
                    u for u in result
                    if u.employment_status.value == filters["employment_status"]
                ]
        return result

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        result = self._load_courses()
        if filters and "mandatory" in filters:
            result = [c for c in result if c.mandatory == filters["mandatory"]]
        return result

    async def get_enrollments(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[Enrollment]:
        result = self._load_enrollments()
        if user_ids:
            result = [e for e in result if e.user_id in user_ids]
        if course_ids:
            result = [e for e in result if e.course_id in course_ids]
        return result

    async def get_learning_records(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[LearningRecord]:
        result = self._load_learning_records()
        if user_ids:
            result = [r for r in result if r.user_id in user_ids]
        if course_ids:
            result = [r for r in result if r.course_id in course_ids]
        return result

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        # CSV exports are a read-only data source; there is nothing to
        # send a reminder through.
        return False
