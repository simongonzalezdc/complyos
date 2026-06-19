"""D2L Brightspace (Valence) read-only connector.

Brightspace exposes a documented REST API under ``<base_url>/d2l/api/{lp|le}/{ver}/...``
(``lp`` = Learning Platform for users/enrollments/completion, ``le`` = Learning
Environment for grades). This connector is intentionally read-only: it pulls
course enrollments, completion, and final grades for a course (org unit) and
normalizes them into the shared :class:`LearningRecord` contract. It does not
write back to Brightspace (``trigger_reminder`` is a no-op), matching the
Canvas/Cornerstone/SuccessFactors read-only posture.

Auth mirrors the Cornerstone OAuth2 client-credentials token machinery (token
fetch + refresh with an expiry buffer). Brightspace's production OAuth2 uses a
JWT client-assertion against ``auth.brightspace.com``; this connector keeps the
same shared-secret ``client_credentials`` shape as the other workforce OAuth
connectors and points ``token_url`` at the D2L auth host by default.

Brightspace paginates list responses with bookmark-based ``PagedResultSet``
objects (``PagingInfo.Bookmark`` + ``PagingInfo.HasMoreItems``); this connector
follows the bookmark until ``HasMoreItems`` is false.

Environment variables:
    BRIGHTSPACE_BASE_URL: e.g. https://school.brightspace.com
    BRIGHTSPACE_CLIENT_ID: OAuth2 client id
    BRIGHTSPACE_CLIENT_SECRET: OAuth2 client secret
    BRIGHTSPACE_TOKEN_URL: optional override for the OAuth2 token endpoint
    BRIGHTSPACE_ORG_UNIT_ID: optional default course (org unit) scope
    BRIGHTSPACE_LP_VERSION: optional Learning Platform API version (default 1.49)
    BRIGHTSPACE_LE_VERSION: optional Learning Environment API version (default 1.82)
"""

from __future__ import annotations

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

# Safe floor API versions (lp 1.46-1.48 / le 1.75-1.81 are deprecated).
_DEFAULT_LP_VERSION = "1.49"
_DEFAULT_LE_VERSION = "1.82"
_DEFAULT_TOKEN_URL = "https://auth.brightspace.com/core/connect/token"


class BrightspaceConnector(LMSConnector):
    """Read-only connector for the D2L Brightspace (Valence) REST API (Campus track)."""

    name = "brightspace"

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        token_url: str | None = None,
        org_unit_id: str | None = None,
        lp_version: str | None = None,
        le_version: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BRIGHTSPACE_BASE_URL") or "").rstrip("/")
        self.client_id = client_id or os.getenv("BRIGHTSPACE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("BRIGHTSPACE_CLIENT_SECRET")
        self.token_url = (
            token_url or os.getenv("BRIGHTSPACE_TOKEN_URL") or _DEFAULT_TOKEN_URL
        )
        self.org_unit_id = org_unit_id or os.getenv("BRIGHTSPACE_ORG_UNIT_ID")
        self.lp_version = lp_version or os.getenv("BRIGHTSPACE_LP_VERSION") or _DEFAULT_LP_VERSION
        self.le_version = le_version or os.getenv("BRIGHTSPACE_LE_VERSION") or _DEFAULT_LE_VERSION
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
        scope = self._org_unit_scope()
        params: dict[str, Any] = dict(filters or {})
        items = await self._paginate(
            f"/d2l/api/lp/{self.lp_version}/enrollments/orgUnits/{scope}/users/", params
        )
        return [_parse_user(item) for item in items]

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        params: dict[str, Any] = dict(filters or {})
        items = await self._paginate(
            f"/d2l/api/lp/{self.lp_version}/orgstructure/", params
        )
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
        scopes = course_ids or ([self.org_unit_id] if self.org_unit_id else [])
        if not scopes:
            raise ValueError(
                "Brightspace learning-record pulls require a course (org unit) scope: "
                "pass course_ids or set BRIGHTSPACE_ORG_UNIT_ID"
            )
        wanted = {str(u) for u in user_ids} if user_ids else None
        records: list[LearningRecord] = []
        for org_unit in scopes:
            records.extend(await self._org_unit_records(str(org_unit), wanted))
        return records

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        # Read-only connector: ComplyOS does not write notifications into Brightspace.
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _org_unit_records(
        self, org_unit_id: str, wanted: set[str] | None
    ) -> list[LearningRecord]:
        """Pull enrollments + final grades for one org unit and normalize each.

        Brightspace exposes the per-user final grade via the LE grades endpoint;
        each enrollment ties one learner to one org unit with a role, and the
        bulk final-grade values carry the displayed/points score.
        """
        enrollments = await self._paginate(
            f"/d2l/api/lp/{self.lp_version}/enrollments/orgUnits/{org_unit_id}/users/", {}
        )
        grades = await self._paginate(
            f"/d2l/api/le/{self.le_version}/{org_unit_id}/grades/final/values/", {}
        )
        grade_by_user = {
            str(g.get("UserId")): g for g in grades if g.get("UserId") is not None
        }

        records: list[LearningRecord] = []
        for item in enrollments:
            user_id = _enrollment_user_id(item)
            if wanted is not None and user_id not in wanted:
                continue
            grade = grade_by_user.get(user_id, {})
            records.append(_parse_enrollment_record(item, org_unit_id, grade))
        return records

    async def _paginate(
        self, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Follow Brightspace bookmark pagination until ``HasMoreItems`` is false.

        A bookmark that repeats is treated as the end of pagination so a
        misbehaving server cannot cause an infinite loop (fail-safe for a
        compliance pull).
        """
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        query = dict(params)
        while True:
            response = await self.client.get(
                path, params=query, headers=await self._headers()
            )
            response.raise_for_status()
            payload = response.json()
            items.extend(_as_items(payload))
            bookmark, has_more = _paging_info(payload)
            if not has_more or not bookmark or bookmark in seen:
                break
            seen.add(bookmark)
            query = {**params, "bookmark": bookmark}
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
            raise ValueError("Brightspace OAuth configuration is incomplete")

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

    def _org_unit_scope(self) -> str:
        if not self.org_unit_id:
            raise ValueError(
                "Brightspace user/enrollment pulls require an org unit scope: "
                "set BRIGHTSPACE_ORG_UNIT_ID"
            )
        return str(self.org_unit_id)


def _as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        # PagedResultSet wrapper: {"Items": [...], "PagingInfo": {...}}.
        if isinstance(payload.get("Items"), list):
            return [item for item in payload["Items"] if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _paging_info(payload: Any) -> tuple[str | None, bool]:
    info = payload.get("PagingInfo") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        return None, False
    bookmark = info.get("Bookmark")
    return (str(bookmark) if bookmark not in (None, "") else None), bool(info.get("HasMoreItems"))


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _enrollment_user_id(item: dict[str, Any]) -> str:
    user = _nested_dict(item.get("User"))
    return str(item.get("UserId") or user.get("Identifier") or "")


def _parse_user(item: dict[str, Any]) -> User:
    user = _nested_dict(item.get("User")) or item
    name = str(user.get("DisplayName") or "")
    first, _, last = name.partition(" ")
    return User(
        id=str(user.get("Identifier") or user.get("UserId") or ""),
        employee_id=str(user.get("OrgDefinedId") or user.get("Identifier") or ""),
        email=str(user.get("EmailAddress") or ""),
        first_name=str(user.get("FirstName") or first or ""),
        last_name=str(user.get("LastName") or last or ""),
        department="",
        region="",
        hire_date=date.today(),
        employment_status=EmploymentStatus.ACTIVE,
        custom_attributes={"source_system": "brightspace"},
    )


def _parse_course(item: dict[str, Any]) -> Course:
    org_unit = _nested_dict(item.get("OrgUnit")) or item
    course_id = str(org_unit.get("Identifier") or org_unit.get("Id") or "")
    return Course(
        id=course_id,
        code=str(org_unit.get("Code") or course_id),
        title=str(org_unit.get("Name") or org_unit.get("Code") or course_id),
        description=org_unit.get("Description"),
        mandatory=False,
        category=_nested_dict(org_unit.get("Type")).get("Name"),
    )


def _parse_enrollment_record(
    item: dict[str, Any], org_unit_id: str, grade: dict[str, Any]
) -> LearningRecord:
    """Normalize a Brightspace enrollment + final grade into a LearningRecord."""
    user_id = _enrollment_user_id(item)
    completion = _nested_dict(item.get("Completion"))
    completed = bool(item.get("IsCompleted") or completion.get("Completion"))
    completed_at = _parse_datetime(item.get("CompletionDate") or completion.get("CompletionDate"))
    status = LearningRecordStatus.COMPLETED if completed else _access_status(item)
    record_id = str(item.get("Id") or f"{org_unit_id}:{user_id}" or _hash_payload(item))
    merged: dict[str, Any] = {**item, "FinalGrade": grade} if grade else dict(item)
    return LearningRecord(
        id=record_id,
        user_id=user_id,
        course_id=str(item.get("OrgUnitId") or org_unit_id),
        source_system="brightspace",
        source_record_id=record_id,
        status=status,
        completed_date=completed_at,
        completion_percentage=100.0 if status == LearningRecordStatus.COMPLETED else 0.0,
        score=_grade_score(grade),
        raw_source_hash=_hash_payload(merged),
        source_payload=merged,
    )


def _access_status(item: dict[str, Any]) -> LearningRecordStatus:
    access = _nested_dict(item.get("Access"))
    if access.get("IsActive") is False:
        return LearningRecordStatus.NOT_STARTED
    return LearningRecordStatus.IN_PROGRESS


def _grade_score(grade: dict[str, Any]) -> float | None:
    if not grade:
        return None
    numerator = grade.get("PointsNumerator")
    denominator = grade.get("PointsDenominator")
    if numerator is not None and denominator:
        try:
            return round(float(numerator) / float(denominator) * 100.0, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return _optional_float(grade.get("DisplayedGrade"))


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
