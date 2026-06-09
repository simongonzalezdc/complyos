"""Base connector abstraction for LMS platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from complyos.models.domain import Course, Enrollment, User


class LMSConnector(ABC):
    """Abstract base for all LMS connectors."""

    name: str = "abstract"

    @abstractmethod
    async def authenticate(self) -> bool:
        """Verify connector can reach the LMS."""
        ...

    @abstractmethod
    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        """Fetch users, optionally filtered."""
        ...

    @abstractmethod
    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        """Fetch courses, optionally filtered."""
        ...

    @abstractmethod
    async def get_enrollments(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[Enrollment]:
        """Fetch enrollments, optionally filtered by user or course."""
        ...

    @abstractmethod
    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        """Send a reminder to a user about a course."""
        ...

    async def health_check(self) -> dict[str, Any]:
        """Return connector health status."""
        try:
            auth_ok = await self.authenticate()
            return {
                "connector": self.name,
                "authenticated": auth_ok,
                "status": "healthy" if auth_ok else "auth_failed",
            }
        except Exception as e:
            return {
                "connector": self.name,
                "authenticated": False,
                "status": "error",
                "error": str(e),
            }
