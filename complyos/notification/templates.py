"""Plain-text email templates for ComplyOS notifications."""

from __future__ import annotations

from complyos.models.domain import ComplianceGap, Course, User


def render_reminder(
    user: User,
    course: Course,
    gap: ComplianceGap | None = None,
) -> tuple[str, str]:
    """Return (subject, body) for a reminder email."""
    subject = f"Action Required: Complete {course.title}"

    lines = [
        f"Hi {user.first_name},",
        "",
        f"You have a pending training requirement: {course.title}.",
    ]

    if gap and gap.days_overdue:
        lines.append(f"This training is {gap.days_overdue} day(s) overdue.")

    lines.extend([
        "",
        "Please complete this course as soon as possible to maintain compliance.",
        "",
        "If you have any questions, contact your manager or the L&D team.",
        "",
        "— ComplyOS",
    ])

    return subject, "\n".join(lines)


def render_manager_notification(
    user: User,
    course: Course,
    gap: ComplianceGap | None = None,
) -> tuple[str, str]:
    """Return (subject, body) for a manager notification email."""
    subject = f"Compliance Alert: {user.full_name} — {course.title}"

    lines = [
        "Manager Notification — Critical Compliance Gap",
        "",
        f"Employee: {user.full_name} ({user.email})",
        f"Department: {user.department}",
        f"Missing Course: {course.title}",
    ]

    if gap and gap.days_overdue:
        lines.append(f"Days Overdue: {gap.days_overdue}")

    lines.extend([
        "",
        "Please follow up with this employee to ensure timely completion.",
        "",
        "— ComplyOS",
    ])

    return subject, "\n".join(lines)
