"""Workday Learning REST API connector."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import httpx

from complyos.connectors.base import LMSConnector
from complyos.models.domain import Course, EmploymentStatus, Enrollment, EnrollmentStatus, User


class WorkdayConnector(LMSConnector):
    """Connector for Workday Learning REST API.

    Environment variables:
        WORKDAY_BASE_URL: e.g. https://wd2-impl-services1.workday.com/tenant
        WORKDAY_USERNAME: Integration system username
        WORKDAY_PASSWORD: Integration system password
    """

    name = "workday"

    def __init__(self, base_url: str | None = None, username: str | None = None, password: str | None = None):
        self.base_url = (base_url or os.getenv("WORKDAY_BASE_URL", "")).rstrip("/")
        self.username = username or os.getenv("WORKDAY_USERNAME", "")
        self.password = password or os.getenv("WORKDAY_PASSWORD", "")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=(self.username, self.password),
                timeout=30.0,
            )
        return self._client

    async def authenticate(self) -> bool:
        if not self.base_url or not self.username:
            return False
        try:
            response = await self.client.get(f"{self.base_url}/learning/v1/workers", params={"limit": 1})
            return response.status_code == 200
        except Exception:
            return False

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        params: dict[str, Any] = {"limit": 1000}
        if filters:
            if "department" in filters:
                params["department"] = filters["department"]
            if "region" in filters:
                params["region"] = filters["region"]

        response = await self.client.get(f"{self.base_url}/learning/v1/workers", params=params)
        response.raise_for_status()
        data = response.json().get("data", [])

        return [_parse_workday_user(u) for u in data]

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        params: dict[str, Any] = {"limit": 1000}
        if filters and "mandatory" in filters:
            params["mandatoryOnly"] = "true"

        response = await self.client.get(f"{self.base_url}/learning/v1/courses", params=params)
        response.raise_for_status()
        data = response.json().get("data", [])

        return [_parse_workday_course(c) for c in data]

    async def get_enrollments(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[Enrollment]:
        params: dict[str, Any] = {"limit": 1000}
        if user_ids:
            params["worker"] = ",".join(user_ids)
        if course_ids:
            params["course"] = ",".join(course_ids)

        response = await self.client.get(f"{self.base_url}/learning/v1/enrollments", params=params)
        response.raise_for_status()
        data = response.json().get("data", [])

        return [_parse_workday_enrollment(e) for e in data]

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        payload = {
            "worker": {"id": user_id},
            "course": {"id": course_id},
            "notificationType": "REMINDER",
        }
        response = await self.client.post(
            f"{self.base_url}/learning/v1/notifications", json=payload
        )
        return response.status_code in (200, 201)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


def _parse_workday_user(data: dict[str, Any]) -> User:
    status_map = {
        "Active": EmploymentStatus.ACTIVE,
        "Terminated": EmploymentStatus.TERMINATED,
        "On_Leave": EmploymentStatus.ON_LEAVE,
        "Contractor": EmploymentStatus.CONTRACTOR,
    }
    return User(
        id=data.get("id", ""),
        employee_id=data.get("employeeID", data.get("id", "")),
        email=data.get("primaryWorkEmail", ""),
        first_name=data.get("firstName", ""),
        last_name=data.get("lastName", ""),
        department=data.get("supervisoryOrganization", {}).get("descriptor", "Unknown"),
        region=data.get("location", {}).get("descriptor", "Unknown"),
        hire_date=_parse_date(data.get("hireDate")) or date.today(),
        employment_status=status_map.get(data.get("workerStatus", ""), EmploymentStatus.ACTIVE),
        manager_id=data.get("manager", {}).get("id"),
        job_title=data.get("jobProfile", {}).get("descriptor"),
        custom_attributes={k: v for k, v in data.items() if k not in {
            "id", "employeeID", "firstName", "lastName", "primaryWorkEmail",
            "supervisoryOrganization", "location", "hireDate", "workerStatus", "manager", "jobProfile"
        }},
    )


def _parse_workday_course(data: dict[str, Any]) -> Course:
    return Course(
        id=data.get("id", ""),
        code=data.get("courseNumber", data.get("id", "")),
        title=data.get("title", ""),
        description=data.get("description", None),
        duration_minutes=data.get("duration", None),
        mandatory=data.get("required", False),
        category=data.get("topic", None),
    )


def _parse_workday_enrollment(data: dict[str, Any]) -> Enrollment:
    status_map = {
        "Not_Started": EnrollmentStatus.NOT_STARTED,
        "In_Progress": EnrollmentStatus.IN_PROGRESS,
        "Completed": EnrollmentStatus.COMPLETED,
        "Overdue": EnrollmentStatus.OVERDUE,
        "Exempt": EnrollmentStatus.EXEMPT,
    }
    return Enrollment(
        id=data.get("id", ""),
        user_id=data.get("worker", {}).get("id", ""),
        course_id=data.get("course", {}).get("id", ""),
        status=status_map.get(data.get("status", ""), EnrollmentStatus.NOT_STARTED),
        assigned_date=_parse_datetime(data.get("assignedDate")),
        due_date=_parse_date(data.get("dueDate")),
        completed_date=_parse_datetime(data.get("completedDate")),
        completion_percentage=float(data.get("percentComplete", 0)),
        score=float(data.get("score", 0)) if data.get("score") is not None else None,
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
