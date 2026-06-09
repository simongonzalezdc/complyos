"""Remediation engine for acting on compliance gaps."""

from __future__ import annotations

from complyos.connectors.base import LMSConnector
from complyos.models.domain import ComplianceGap, RemediationAction


class RemediationEngine:
    """Process compliance gaps and apply remediation actions."""

    def __init__(self, connector: LMSConnector) -> None:
        self.connector = connector

    async def remediate_gaps(
        self,
        gaps: list[ComplianceGap],
        *,
        auto_remind: bool = True,
        auto_enroll: bool = False,
        notify_manager: bool = False,
    ) -> list[RemediationAction]:
        """Apply remediation actions to a list of compliance gaps.

        Args:
            gaps: Compliance gaps to remediate
            auto_remind: Send reminder notifications for high/critical gaps
            auto_enroll: Auto-enroll users in missing courses (if supported)
            notify_manager: Notify managers for critical gaps

        Returns:
            List of remediation actions with their status.
        """
        actions: list[RemediationAction] = []

        for gap in gaps:
            for course in gap.missing_courses:
                # Determine actions based on severity
                if gap.severity == "critical":
                    if auto_remind:
                        actions.append(await self._send_reminder(gap.user.id, course.id))
                    if notify_manager and gap.user.manager_id:
                        actions.append(
                            await self._notify_manager(
                                gap.user.manager_id, gap.user.id, course.id
                            )
                        )
                elif gap.severity == "high" and auto_remind:
                    actions.append(await self._send_reminder(gap.user.id, course.id))
                elif gap.severity == "medium":
                    # Log for tracking but don't auto-act
                    actions.append(
                        RemediationAction(
                            action_type="log",
                            user_id=gap.user.id,
                            course_id=course.id,
                            status="logged",
                        )
                    )
                # low severity: no action

                if auto_enroll:
                    actions.append(await self._auto_enroll(gap.user.id, course.id))

        return actions

    async def _send_reminder(self, user_id: str, course_id: str) -> RemediationAction:
        """Send a reminder notification to a user."""
        try:
            success = await self.connector.trigger_reminder(user_id, course_id)
            return RemediationAction(
                action_type="reminder",
                user_id=user_id,
                course_id=course_id,
                status="sent" if success else "failed",
                error_message=None if success else "Connector returned failure",
            )
        except Exception as e:
            return RemediationAction(
                action_type="reminder",
                user_id=user_id,
                course_id=course_id,
                status="failed",
                error_message=str(e),
            )

    async def _notify_manager(
        self, manager_id: str, user_id: str, course_id: str
    ) -> RemediationAction:
        """Notify a manager about a critical gap.

        This is a placeholder — real implementation would use email/Slack.
        """
        return RemediationAction(
            action_type="notify_manager",
            user_id=user_id,
            course_id=course_id,
            status="sent",
        )

    async def _auto_enroll(self, user_id: str, course_id: str) -> RemediationAction:
        """Auto-enroll a user in a course.

        This is a placeholder — real implementation would call LMS enrollment API.
        """
        return RemediationAction(
            action_type="enroll",
            user_id=user_id,
            course_id=course_id,
            status="pending",
        )
