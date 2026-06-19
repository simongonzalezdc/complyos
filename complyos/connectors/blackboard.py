"""Blackboard Learn read-only connector.

Blackboard Learn exposes a documented REST API under
``<base_url>/learn/api/public/{v1|v2|v3}/...`` and authenticates with an OAuth2
client-credentials token (HTTP Basic ``application_key:application_secret`` on
the token request). This connector is intentionally read-only: it pulls course
memberships and gradebook grades for a course and normalizes them into the
shared :class:`LearningRecord` contract. It does not write back to Blackboard
(``trigger_reminder`` is a no-op), matching the read-only posture of the other
connectors.

Blackboard paginates list responses with a ``paging.nextPage`` relative URL;
this connector follows ``nextPage`` until it is absent. Grades expose an
``exempt`` flag, a ``status`` (e.g. ``Graded``), a numeric ``score``, and the
owning column carries the ``grading.due`` due date — all mapped onto the record.

Environment variables:
    BLACKBOARD_BASE_URL: e.g. https://blackboard.school.edu
    BLACKBOARD_CLIENT_ID: OAuth2 application key
    BLACKBOARD_CLIENT_SECRET: OAuth2 application secret
    BLACKBOARD_COURSE_ID: optional default course scope for record pulls
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date, datetime, timedelta
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

_TOKEN_PATH = "/learn/api/public/v1/oauth2/token"


class BlackboardConnector(LMSConnector):
    """Read-only connector for the Blackboard Learn REST API (Campus track)."""

    name = "blackboard"

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        course_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BLACKBOARD_BASE_URL") or "").rstrip("/")
        self.client_id = client_id or os.getenv("BLACKBOARD_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("BLACKBOARD_CLIENT_SECRET")
        self.course_id = course_id or os.getenv("BLACKBOARD_COURSE_ID")
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self._client

    async def authenticate(self) -> bool:
        try:
            return bool(await self._token())
        except Exception:
            return False

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        course = self._course_scope(filters)
        params: dict[str, Any] = {"expand": "user"}
        if filters:
            params.update({k: v for k, v in filters.items() if k != "courseid"})
        items = await self._paginate(
            f"/learn/api/public/v1/courses/{course}/users", params
        )
        return [_parse_user(item) for item in items]

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        items = await self._paginate("/learn/api/public/v3/courses", dict(filters or {}))
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
                "Blackboard learning-record pulls require a course scope: pass course_ids "
                "or set BLACKBOARD_COURSE_ID"
            )
        wanted = {str(u) for u in user_ids} if user_ids else None
        records: list[LearningRecord] = []
        for course in scopes:
            records.extend(await self._course_records(str(course), wanted))
        return records

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        # Read-only connector: ComplyOS does not write notifications into Blackboard.
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _course_records(
        self, course_id: str, wanted: set[str] | None
    ) -> list[LearningRecord]:
        """Pull memberships + gradebook grades for one course and normalize each.

        Blackboard exposes per-column grades via the v2 gradebook endpoints; each
        grade ties one learner to one column with a status, score, ``exempt``
        flag, and the column's ``grading.due`` due date. Memberships seed a record
        for every enrolled learner so a never-graded learner is still visible.
        """
        memberships = await self._paginate(
            f"/learn/api/public/v1/courses/{course_id}/users", {"expand": "user"}
        )
        columns = await self._paginate(
            f"/learn/api/public/v2/courses/{course_id}/gradebook/columns", {}
        )

        records: list[LearningRecord] = []
        for item in memberships:
            user_id = str(item.get("userId") or "")
            if wanted is not None and user_id not in wanted:
                continue
            records.append(_parse_membership_record(item, course_id))

        for column in columns:
            column_id = str(column.get("id") or "")
            if not column_id:
                continue
            due = _column_due(column)
            grades = await self._paginate(
                f"/learn/api/public/v2/courses/{course_id}/gradebook/columns/{column_id}/users",
                {},
            )
            for grade in grades:
                user_id = str(grade.get("userId") or "")
                if wanted is not None and user_id not in wanted:
                    continue
                records.append(_parse_grade_record(grade, course_id, column_id, due))
        return records

    async def _paginate(
        self, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Follow Blackboard ``paging.nextPage`` relative URLs until absent.

        A ``nextPage`` that repeats is treated as the end of pagination so a
        misbehaving server cannot cause an infinite loop (fail-safe for a
        compliance pull).
        """
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        next_url: str | None = None
        first = True
        while first or next_url:
            if first:
                response = await self.client.get(
                    path, params=params, headers=await self._headers()
                )
                first = False
            else:
                assert next_url is not None
                response = await self.client.get(next_url, headers=await self._headers())
            response.raise_for_status()
            payload = response.json()
            items.extend(_results(payload))
            next_url = _next_page(payload)
            if not next_url or next_url in seen:
                break
            seen.add(next_url)
        return items

    async def _headers(self) -> dict[str, str]:
        token = await self._token()
        return {"Authorization": f"Bearer {token}"}

    async def _token(self) -> str:
        if (
            self._access_token
            and self._token_expires_at
            and self._token_expires_at > datetime.now() + timedelta(seconds=30)
        ):
            return self._access_token
        if not (self.base_url and self.client_id and self.client_secret):
            raise ValueError("Blackboard OAuth configuration is incomplete")

        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        response = await self.client.post(
            _TOKEN_PATH,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = str(payload["access_token"])
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        return self._access_token

    def _course_scope(self, filters: dict[str, Any] | None) -> str:
        if filters and filters.get("courseid"):
            return str(filters["courseid"])
        if self.course_id:
            return str(self.course_id)
        raise ValueError(
            "Blackboard membership pulls require a course scope: pass courseid in "
            "filters or set BLACKBOARD_COURSE_ID"
        )


def _results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _next_page(payload: Any) -> str | None:
    paging = payload.get("paging") if isinstance(payload, dict) else None
    if not isinstance(paging, dict):
        return None
    next_page = paging.get("nextPage")
    return str(next_page) if next_page else None


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_user(item: dict[str, Any]) -> User:
    user = _nested_dict(item.get("user"))
    name = _nested_dict(user.get("name"))
    contact = _nested_dict(user.get("contact"))
    user_id = str(item.get("userId") or user.get("id") or "")
    return User(
        id=user_id,
        employee_id=str(user.get("studentId") or user.get("userName") or user_id),
        email=str(contact.get("email") or ""),
        first_name=str(name.get("given") or ""),
        last_name=str(name.get("family") or ""),
        department="",
        region="",
        hire_date=date.today(),
        employment_status=EmploymentStatus.ACTIVE,
        custom_attributes={"source_system": "blackboard"},
    )


def _parse_course(item: dict[str, Any]) -> Course:
    course_id = str(item.get("id") or item.get("courseId") or "")
    return Course(
        id=course_id,
        code=str(item.get("courseId") or item.get("externalId") or course_id),
        title=str(item.get("name") or item.get("courseId") or course_id),
        description=item.get("description"),
        mandatory=False,
        category=_nested_dict(item.get("availability")).get("available"),
    )


def _parse_membership_record(item: dict[str, Any], course_id: str) -> LearningRecord:
    """Normalize a Blackboard course membership into a baseline LearningRecord."""
    user_id = str(item.get("userId") or "")
    available = _nested_dict(item.get("availability")).get("available")
    status = (
        LearningRecordStatus.IN_PROGRESS
        if available == "Yes"
        else LearningRecordStatus.NOT_STARTED
    )
    record_id = f"{course_id}:{user_id}"
    return LearningRecord(
        id=record_id,
        user_id=user_id,
        course_id=course_id,
        source_system="blackboard",
        source_record_id=record_id,
        status=status,
        assigned_date=_parse_datetime(item.get("created")),
        completion_percentage=0.0,
        raw_source_hash=_hash_payload(item),
        source_payload=item,
    )


def _parse_grade_record(
    grade: dict[str, Any], course_id: str, column_id: str, due: date | None
) -> LearningRecord:
    """Normalize a Blackboard gradebook grade into a LearningRecord.

    Blackboard grades carry the per-column result: ``status`` (e.g. ``Graded``),
    a numeric ``score``, and an ``exempt`` flag that maps to an exemption. The
    column id is preserved as the source learning item id.
    """
    exempt = bool(grade.get("exempt"))
    status = _grade_status(grade.get("status"), exempt=exempt)
    user_id = str(grade.get("userId") or "")
    record_id = f"{course_id}:{column_id}:{user_id}"
    return LearningRecord(
        id=record_id,
        user_id=user_id,
        course_id=column_id or course_id,
        source_system="blackboard",
        source_record_id=record_id,
        status=status,
        due_date=due,
        completed_date=_parse_datetime(grade.get("changeIndexTimestamp")),
        completion_percentage=100.0 if status == LearningRecordStatus.COMPLETED else 0.0,
        score=_optional_float(grade.get("score")),
        exempt=exempt,
        raw_source_hash=_hash_payload(grade),
        source_payload=grade,
    )


def _grade_status(value: Any, *, exempt: bool) -> LearningRecordStatus:
    if exempt:
        return LearningRecordStatus.EXEMPT
    normalized = str(value or "").strip().lower()
    if normalized == "graded":
        return LearningRecordStatus.COMPLETED
    if normalized in {"needsgrading", "inprogress"}:
        return LearningRecordStatus.IN_PROGRESS
    return LearningRecordStatus.ASSIGNED


def _column_due(column: dict[str, Any]) -> date | None:
    grading = _nested_dict(column.get("grading"))
    return _parse_date(grading.get("due"))


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
