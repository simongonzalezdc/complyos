"""Cornerstone Learning connector."""

from __future__ import annotations

import hashlib
import json
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


class CornerstoneConnector(LMSConnector):
    """Connector for Cornerstone Learning APIs."""

    name = "cornerstone"

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        token_url: str | None = None,
    ) -> None:
        import os

        self.base_url = (base_url or os.getenv("CORNERSTONE_BASE_URL") or "").rstrip("/")
        self.client_id = client_id or os.getenv("CORNERSTONE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CORNERSTONE_CLIENT_SECRET")
        self.token_url = token_url or f"{self.base_url}/services/api/oauth2/token"
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
        response = await self.client.get(
            "/services/api/x/users/v1/employees",
            headers=await self._headers(),
            params=filters or {},
        )
        response.raise_for_status()
        return [_parse_user(item) for item in _items(response.json())]

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        response = await self.client.get(
            "/services/api/x/learning/v1/learning-objects",
            headers=await self._headers(),
            params=filters or {},
        )
        response.raise_for_status()
        return [_parse_course(item) for item in _items(response.json())]

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
        params: dict[str, Any] = {}
        if user_ids:
            params["userIds"] = ",".join(user_ids)
        if course_ids:
            params["loIds"] = ",".join(course_ids)
        response = await self.client.get(
            "/services/api/x/learning/v1/transcripts",
            headers=await self._headers(),
            params=params,
        )
        response.raise_for_status()
        return [_parse_learning_record(item) for item in _items(response.json())]

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

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
            raise ValueError("Cornerstone OAuth configuration is incomplete")

        response = await self.client.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = str(payload["access_token"])
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        return self._access_token


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("data", payload.get("value", payload.get("items", [])))
    return list(raw or [])


def _parse_user(item: dict[str, Any]) -> User:
    user_id = str(item.get("id") or item.get("userId") or item.get("ref"))
    status = str(item.get("status", "active")).lower()
    return User(
        id=user_id,
        employee_id=str(item.get("employeeId") or item.get("ref") or user_id),
        email=str(item.get("email") or item.get("emailAddress") or ""),
        first_name=str(item.get("firstName") or item.get("first_name") or ""),
        last_name=str(item.get("lastName") or item.get("last_name") or ""),
        department=str(item.get("department") or item.get("ouName") or ""),
        region=str(item.get("region") or item.get("location") or ""),
        hire_date=_parse_date(item.get("hireDate")) or date.today(),
        employment_status=EmploymentStatus.TERMINATED
        if status in {"inactive", "terminated"}
        else EmploymentStatus.ACTIVE,
        manager_id=item.get("managerId"),
        custom_attributes={"source_system": "cornerstone"},
    )


def _parse_course(item: dict[str, Any]) -> Course:
    course_id = str(item.get("id") or item.get("loId") or item.get("locator"))
    return Course(
        id=course_id,
        code=str(item.get("locator") or item.get("code") or course_id),
        title=str(item.get("title") or item.get("name") or course_id),
        description=item.get("description"),
        duration_minutes=_optional_int(item.get("duration") or item.get("durationMinutes")),
        mandatory=bool(item.get("isRequired", item.get("mandatory", False))),
        category=item.get("type") or item.get("subject"),
    )


def _parse_learning_record(item: dict[str, Any]) -> LearningRecord:
    status = _learning_status(item.get("status"))
    record_id = str(item.get("transcriptId") or item.get("id") or _hash_payload(item))
    return LearningRecord(
        id=record_id,
        user_id=str(item.get("userId") or item.get("user_id")),
        course_id=str(item.get("loId") or item.get("learningObjectId") or item.get("courseId")),
        source_system="cornerstone",
        source_record_id=record_id,
        status=status,
        due_date=_parse_date(item.get("dueDate")),
        completed_date=_parse_datetime(item.get("completionDate") or item.get("completedDate")),
        completion_percentage=100.0 if status == LearningRecordStatus.COMPLETED else 0.0,
        score=_optional_float(item.get("score")),
        raw_source_hash=_hash_payload(item),
        source_payload=item,
    )


def _learning_status(value: Any) -> LearningRecordStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"completed", "complete", "passed"}:
        return LearningRecordStatus.COMPLETED
    if normalized in {"exempt", "waived"}:
        return LearningRecordStatus.EXEMPT
    if normalized in {"in progress", "in_progress", "registered"}:
        return LearningRecordStatus.IN_PROGRESS
    if normalized in {"overdue", "expired"}:
        return LearningRecordStatus.OVERDUE
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


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return None


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
