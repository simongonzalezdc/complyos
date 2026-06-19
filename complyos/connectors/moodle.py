"""Moodle Web Services read-only connector.

Moodle exposes a Web Services REST API where every call hits a single endpoint,
``<base_url>/webservice/rest/server.php``, selecting the operation via a
``wsfunction`` parameter and authenticating with a ``wstoken`` query parameter
(no OAuth). This connector is intentionally read-only: it pulls enrolled users
and per-user course completion for a course and normalizes them into the shared
:class:`LearningRecord` contract. It does not write back to Moodle
(``trigger_reminder`` is a no-op), matching the read-only posture of the other
connectors.

Moodle returns HTTP 200 even on failure, signalling errors with an ``exception``
key in the JSON body. This connector fails closed: an error body is raised as an
:class:`httpx.HTTPStatusError`-equivalent error so a compliance pull never
silently treats an auth/permission failure as "no records".

Environment variables:
    MOODLE_BASE_URL: e.g. https://moodle.school.edu
    MOODLE_TOKEN: Web Services token (wstoken)
    MOODLE_COURSE_ID: optional default course scope for record pulls
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from typing import Any

import httpx

from complyos.connectors.base import LMSConnector
from complyos.models.domain import (
    Course,
    EmploymentStatus,
    Enrollment,
    LearningRecord,
    LearningRecordStatus,
    User,
)

_REST_PATH = "/webservice/rest/server.php"
# core_completion_get_course_completion_status raises this when a course does not
# enable completion tracking; that is "not applicable", not a connector failure.
_COMPLETION_DISABLED_CODES = {
    "errorcoursecompletionnotenabled",
    "completionnotenabled",
    "nocompletionrecords",
}


class MoodleWebServiceError(RuntimeError):
    """Raised when a Moodle Web Service call returns an error body (HTTP 200)."""

    def __init__(self, errorcode: str, message: str) -> None:
        self.errorcode = errorcode
        self.message = message
        super().__init__(f"{errorcode}: {message}")


class MoodleConnector(LMSConnector):
    """Read-only connector for the Moodle Web Services REST API (Campus track)."""

    name = "moodle"

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        course_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("MOODLE_BASE_URL") or "").rstrip("/")
        self.token = token or os.getenv("MOODLE_TOKEN")
        self.course_id = course_id or os.getenv("MOODLE_COURSE_ID")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self._client

    async def authenticate(self) -> bool:
        if not (self.base_url and self.token):
            return False
        try:
            await self._call("core_webservice_get_site_info")
            return True
        except Exception:
            return False

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        course = self._course_scope(filters)
        payload = await self._call(
            "core_enrol_get_enrolled_users", {"courseid": course}
        )
        return [_parse_user(item) for item in _as_items(payload)]

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        payload = await self._call("core_course_get_courses")
        return [_parse_course(item) for item in _as_items(payload)]

    async def get_enrollments(
        self,
        user_ids: list[str] | None = None,
        course_ids: list[str] | None = None,
    ) -> list[Enrollment]:
        records = await self.get_learning_records(user_ids=user_ids, course_ids=course_ids)
        return [record.to_enrollment() for record in records]

    async def get_learning_records(
        self,
        user_ids: list[str] | None = None,
        course_ids: list[str] | None = None,
    ) -> list[LearningRecord]:
        scopes = course_ids or ([self.course_id] if self.course_id else [])
        if not scopes:
            raise ValueError(
                "Moodle learning-record pulls require a course scope: pass course_ids "
                "or set MOODLE_COURSE_ID"
            )
        wanted = {str(u) for u in user_ids} if user_ids else None
        records: list[LearningRecord] = []
        for course in scopes:
            records.extend(await self._course_records(str(course), wanted))
        return records

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        # Read-only connector: ComplyOS does not write notifications into Moodle.
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _course_records(
        self, course_id: str, wanted: set[str] | None
    ) -> list[LearningRecord]:
        """Pull enrolled users + per-user completion for one course and normalize.

        Moodle reports completion per (course, user) via
        ``core_completion_get_course_completion_status``; this connector reads
        the enrolled roster and joins each learner's completion state.
        """
        enrolled = _as_items(
            await self._call("core_enrol_get_enrolled_users", {"courseid": course_id})
        )
        records: list[LearningRecord] = []
        for user in enrolled:
            user_id = str(user.get("id") or "")
            if wanted is not None and user_id not in wanted:
                continue
            completion = await self._completion_status(course_id, user_id)
            records.append(_parse_completion_record(user, course_id, completion))
        return records

    async def _completion_status(
        self, course_id: str, user_id: str
    ) -> dict[str, Any]:
        try:
            payload = await self._call(
                "core_completion_get_course_completion_status",
                {"courseid": course_id, "userid": user_id},
            )
        except MoodleWebServiceError as exc:
            if exc.errorcode in _COMPLETION_DISABLED_CODES:
                return {}
            raise
        status = payload.get("completionstatus") if isinstance(payload, dict) else None
        return status if isinstance(status, dict) else {}

    async def _call(
        self, wsfunction: str, params: dict[str, Any] | None = None
    ) -> Any:
        if not (self.base_url and self.token):
            raise ValueError("Moodle Web Services configuration is incomplete")
        request_params: dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
            **(params or {}),
        }
        response = await self.client.get(_REST_PATH, params=request_params)
        response.raise_for_status()
        payload = response.json()
        # Moodle signals errors with HTTP 200 + an "exception" key; fail closed.
        if isinstance(payload, dict) and "exception" in payload:
            raise MoodleWebServiceError(
                str(payload.get("errorcode") or "unknown"),
                str(payload.get("message") or "Moodle Web Service error"),
            )
        return payload

    def _course_scope(self, filters: dict[str, Any] | None) -> str:
        if filters and filters.get("courseid"):
            return str(filters["courseid"])
        if self.course_id:
            return str(self.course_id)
        raise ValueError(
            "Moodle user pulls require a course scope: pass courseid in filters "
            "or set MOODLE_COURSE_ID"
        )


def _as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _parse_user(item: dict[str, Any]) -> User:
    name = str(item.get("fullname") or "")
    first, _, last = name.partition(" ")
    return User(
        id=str(item.get("id") or ""),
        employee_id=str(item.get("idnumber") or item.get("username") or item.get("id") or ""),
        email=str(item.get("email") or ""),
        first_name=str(item.get("firstname") or first or ""),
        last_name=str(item.get("lastname") or last or ""),
        department=str(item.get("department") or ""),
        region=str(item.get("timezone") or item.get("lang") or ""),
        hire_date=date.today(),
        employment_status=EmploymentStatus.ACTIVE,
        custom_attributes={"source_system": "moodle"},
    )


def _parse_course(item: dict[str, Any]) -> Course:
    course_id = str(item.get("id") or "")
    title = item.get("fullname") or item.get("displayname") or item.get("shortname") or course_id
    return Course(
        id=course_id,
        code=str(item.get("shortname") or item.get("idnumber") or course_id),
        title=str(title),
        description=item.get("summary"),
        mandatory=False,
        category=_optional_str(item.get("format")),
    )


def _parse_completion_record(
    user: dict[str, Any], course_id: str, completion: dict[str, Any]
) -> LearningRecord:
    """Normalize a Moodle enrolled user + course completion into a LearningRecord."""
    user_id = str(user.get("id") or "")
    completed = bool(completion.get("completed"))
    completed_at = _completion_timestamp(completion)
    status = LearningRecordStatus.COMPLETED if completed else _roster_status(user)
    record_id = f"{course_id}:{user_id}"
    merged: dict[str, Any] = {**user, "completionstatus": completion}
    return LearningRecord(
        id=record_id,
        user_id=user_id,
        course_id=course_id,
        source_system="moodle",
        source_record_id=record_id,
        status=status,
        completed_date=completed_at,
        completion_percentage=100.0 if completed else 0.0,
        raw_source_hash=_hash_payload(merged),
        source_payload=merged,
    )


def _roster_status(user: dict[str, Any]) -> LearningRecordStatus:
    # An enrolled-but-not-complete learner is in progress; a suspended one is not started.
    if user.get("suspended") is True:
        return LearningRecordStatus.NOT_STARTED
    return LearningRecordStatus.IN_PROGRESS


def _completion_timestamp(completion: dict[str, Any]) -> datetime | None:
    """Pull the most recent criterion completion time from a completion status."""
    completions = completion.get("completions")
    if not isinstance(completions, list):
        return None
    timestamps = [
        int(c["timecompleted"])
        for c in completions
        if isinstance(c, dict) and isinstance(c.get("timecompleted"), int) and c["timecompleted"]
    ]
    if not timestamps:
        return None
    return datetime.fromtimestamp(max(timestamps), tz=UTC)


def _optional_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
