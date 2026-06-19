"""Canvas LMS (Instructure) read-only connector.

Canvas exposes a documented REST API under ``<base_url>/api/v1/...`` and
authenticates with a Bearer API token (a user-generated access token or an
OAuth2 access token). This connector is intentionally read-only: it pulls
enrollments and submissions/grades for a course or account and normalizes them
into the shared :class:`LearningRecord` contract. It does not write back to
Canvas (``trigger_reminder`` is a no-op), matching the Cornerstone/SuccessFactors
read-only posture.

Canvas paginates list responses with RFC 5988 ``Link`` headers
(``rel="next"``); this connector follows ``next`` links until exhausted.

Environment variables:
    CANVAS_BASE_URL: e.g. https://school.instructure.com
    CANVAS_API_TOKEN: Bearer API access token
    CANVAS_COURSE_ID: optional default course scope for record pulls
    CANVAS_ACCOUNT_ID: optional account scope (used when no course is set)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
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

# RFC 5988 Link header: <url>; rel="next"
_LINK_REL_RE = re.compile(r'<(?P<url>[^>]+)>\s*;\s*rel="(?P<rel>[^"]+)"')

# Canvas caps page size at 100 for most endpoints.
_PAGE_SIZE = 100


class CanvasConnector(LMSConnector):
    """Read-only connector for the Canvas LMS REST API (Campus track)."""

    name = "canvas"

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        *,
        course_id: str | None = None,
        account_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("CANVAS_BASE_URL") or "").rstrip("/")
        self.api_token = api_token or os.getenv("CANVAS_API_TOKEN")
        self.course_id = course_id or os.getenv("CANVAS_COURSE_ID")
        self.account_id = account_id or os.getenv("CANVAS_ACCOUNT_ID")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self._client

    async def authenticate(self) -> bool:
        if not (self.base_url and self.api_token):
            return False
        try:
            response = await self.client.get(
                "/api/v1/users/self",
                headers=self._headers(),
            )
            return response.status_code == 200
        except Exception:
            return False

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        scope = self._account_scope()
        params: dict[str, Any] = {"per_page": _PAGE_SIZE}
        if filters:
            params.update(filters)
        items = await self._paginate(f"/api/v1/accounts/{scope}/users", params)
        return [_parse_user(item) for item in items]

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        scope = self._account_scope()
        params: dict[str, Any] = {"per_page": _PAGE_SIZE}
        if filters:
            params.update(filters)
        items = await self._paginate(f"/api/v1/accounts/{scope}/courses", params)
        return [_parse_course(item) for item in items]

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
                "Canvas learning-record pulls require a course scope: pass course_ids "
                "or set CANVAS_COURSE_ID"
            )
        records: list[LearningRecord] = []
        for course in scopes:
            records.extend(await self._course_records(str(course), user_ids))
        return records

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        # Read-only connector: ComplyOS does not write notifications into Canvas.
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _course_records(
        self, course_id: str, user_ids: list[str] | None
    ) -> list[LearningRecord]:
        """Pull submissions/grades for one course and normalize each into a record.

        Canvas exposes per-student assignment results via the submissions
        endpoint; each submission ties one learner to one assignment with a
        workflow state, score, due date, and excused (exemption) flag.
        """
        enroll_params: dict[str, Any] = {"per_page": _PAGE_SIZE}
        if user_ids:
            enroll_params["user_id"] = [str(u) for u in user_ids]
        sub_params: dict[str, Any] = {"per_page": _PAGE_SIZE, "student_ids": "all"}
        if user_ids:
            sub_params["student_ids"] = [str(u) for u in user_ids]

        enrollments = await self._paginate(
            f"/api/v1/courses/{course_id}/enrollments", enroll_params
        )
        submissions = await self._paginate(
            f"/api/v1/courses/{course_id}/students/submissions", sub_params
        )

        records = [_parse_enrollment_record(item, course_id) for item in enrollments]
        records.extend(_parse_submission_record(item, course_id) for item in submissions)
        return records

    async def _paginate(
        self, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Follow Canvas RFC 5988 ``Link`` pagination until the ``next`` rel ends.

        A ``next`` link that points back to an already-fetched URL is treated as
        the end of pagination so a misbehaving server cannot cause an infinite
        loop (fail-safe for a compliance pull).
        """
        items: list[dict[str, Any]] = []
        response = await self.client.get(path, params=params, headers=self._headers())
        seen: set[str] = set()
        while True:
            response.raise_for_status()
            items.extend(_as_items(response.json()))
            seen.add(str(response.request.url))
            next_url = _next_link(response.headers.get("Link"))
            if not next_url or next_url in seen:
                break
            response = await self.client.get(next_url, headers=self._headers())
        return items

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def _account_scope(self) -> str:
        return str(self.account_id) if self.account_id else "self"


def _as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for match in _LINK_REL_RE.finditer(link_header):
        if match.group("rel") == "next":
            return match.group("url")
    return None


def _parse_user(item: dict[str, Any]) -> User:
    name = str(item.get("name") or item.get("sortable_name") or "")
    first, _, last = name.partition(" ")
    sis_id = item.get("sis_user_id")
    return User(
        id=str(item.get("id") or item.get("sis_user_id") or ""),
        employee_id=str(sis_id or item.get("id") or ""),
        email=str(item.get("email") or item.get("login_id") or ""),
        first_name=str(item.get("first_name") or first or ""),
        last_name=str(item.get("last_name") or last or ""),
        department=str(item.get("department") or ""),
        region=str(item.get("locale") or item.get("time_zone") or ""),
        hire_date=_parse_date(item.get("created_at")) or date.today(),
        employment_status=EmploymentStatus.ACTIVE,
        custom_attributes={"source_system": "canvas"},
    )


def _parse_course(item: dict[str, Any]) -> Course:
    course_id = str(item.get("id") or item.get("sis_course_id") or "")
    return Course(
        id=course_id,
        code=str(item.get("course_code") or item.get("sis_course_id") or course_id),
        title=str(item.get("name") or item.get("course_code") or course_id),
        description=item.get("public_description") or item.get("description"),
        mandatory=False,
        category=item.get("course_format") or item.get("workflow_state"),
    )


def _parse_enrollment_record(item: dict[str, Any], course_id: str) -> LearningRecord:
    """Normalize a Canvas course enrollment into a LearningRecord."""
    status = _enrollment_status(item.get("enrollment_state"))
    record_id = str(item.get("id") or _hash_payload(item))
    user = _nested_dict(item.get("user"))
    grades = _nested_dict(item.get("grades"))
    user_id = str(item.get("user_id") or user.get("id") or "")
    return LearningRecord(
        id=record_id,
        user_id=user_id,
        course_id=str(item.get("course_id") or course_id),
        source_system="canvas",
        source_record_id=record_id,
        status=status,
        assigned_date=_parse_datetime(item.get("created_at")),
        completed_date=_parse_datetime(item.get("completed_at")),
        completion_percentage=100.0 if status == LearningRecordStatus.COMPLETED else 0.0,
        score=_optional_float(grades.get("current_score") or grades.get("final_score")),
        exempt=status == LearningRecordStatus.EXEMPT,
        raw_source_hash=_hash_payload(item),
        source_payload=item,
    )


def _parse_submission_record(item: dict[str, Any], course_id: str) -> LearningRecord:
    """Normalize a Canvas assignment submission/grade into a LearningRecord.

    Canvas submissions carry the per-assignment result: workflow state, score,
    due date (``cached_due_date``), and an ``excused`` flag that maps to an
    exemption. The assignment id is preserved as the source learning item id.
    """
    excused = bool(item.get("excused"))
    status = _submission_status(item.get("workflow_state"), excused=excused)
    record_id = str(item.get("id") or _hash_payload(item))
    assignment_id = str(item.get("assignment_id") or "")
    return LearningRecord(
        id=record_id,
        user_id=str(item.get("user_id") or ""),
        course_id=assignment_id or str(item.get("course_id") or course_id),
        source_system="canvas",
        source_record_id=record_id,
        status=status,
        due_date=_parse_date(item.get("cached_due_date")),
        completed_date=_parse_datetime(item.get("submitted_at") or item.get("graded_at")),
        completion_percentage=100.0 if status == LearningRecordStatus.COMPLETED else 0.0,
        score=_optional_float(item.get("score")),
        exempt=excused,
        raw_source_hash=_hash_payload(item),
        source_payload=item,
    )


def _enrollment_status(value: Any) -> LearningRecordStatus:
    normalized = str(value or "").strip().lower()
    if normalized == "completed":
        return LearningRecordStatus.COMPLETED
    if normalized == "active":
        return LearningRecordStatus.IN_PROGRESS
    if normalized in {"invited", "creation_pending", "pending"}:
        return LearningRecordStatus.NOT_STARTED
    return LearningRecordStatus.ASSIGNED


def _submission_status(value: Any, *, excused: bool) -> LearningRecordStatus:
    if excused:
        return LearningRecordStatus.EXEMPT
    normalized = str(value or "").strip().lower()
    if normalized == "graded":
        return LearningRecordStatus.COMPLETED
    if normalized in {"submitted", "pending_review"}:
        return LearningRecordStatus.IN_PROGRESS
    if normalized == "unsubmitted":
        return LearningRecordStatus.NOT_STARTED
    return LearningRecordStatus.ASSIGNED


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
