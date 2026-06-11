"""Unit tests for the CSV file connector."""

from __future__ import annotations

from pathlib import Path

from complyos.connectors.csv_file import CSVConnector
from complyos.models.domain import EmploymentStatus, EnrollmentStatus, LearningRecordStatus

CANONICAL_USERS = """id,employee_id,email,first_name,last_name,department,region,hire_date,\
employment_status
u1,E001,alice@example.com,Alice,Smith,Engineering,US,2024-01-15,active
u2,E002,bob@example.com,Bob,Jones,HR,MX,2023-06-01,active
u3,E003,eve@example.com,Eve,Brown,Engineering,US,2022-03-10,terminated
"""

CANONICAL_COURSES = """id,code,title,mandatory,category
c1,SEC-101,Security Basics,true,Compliance
c2,LEAD-201,Leadership,false,Development
"""

CANONICAL_ENROLLMENTS = """id,user_id,course_id,status,due_date,completion_percentage
e1,u1,c1,completed,2025-01-01,100
e2,u2,c1,in_progress,2025-06-01,40
"""

# Cornerstone/Canvas-style export: different headers, different vocab
ALIASED_USERS = """User ID,Employee Number,Email Address,Given Name,Surname,Dept,Location,\
Start Date,Employee Status
u1,E001,alice@example.com,Alice,Smith,Engineering,US,01/15/2024,active
"""

ALIASED_COURSES = """Course ID,Course Code,Course Name,Required
c1,SEC-101,Security Basics,Yes
"""

ALIASED_ENROLLMENTS = """Registration ID,Learner ID,Course ID,Completion Status,Deadline,Progress
e1,u1,c1,Passed,01/01/2025,100%
"""


LEARNING_RECORD_USERS = """id,email,hire_date
u1,student@example.edu,2024-01-15
"""

LEARNING_RECORD_COURSES = """id,code,title,mandatory
c1,FERPA-101,FERPA Basics,true
"""

LEARNING_RECORD_ENROLLMENTS = (
    "Learning Record ID,Learner ID,Course ID,Completion Status,Assigned Date,Due Date,"
    "Completed Date,Score,Expires At,Source System,Source Record ID\n"
    "lr1,u1,c1,Complete,2026-01-01,2026-02-01,2026-01-20,98,2027-01-20,"
    "canvas,canvas-submission-1\n"
)


def write_csv_dir(tmp_path: Path, users: str, courses: str, enrollments: str) -> Path:
    (tmp_path / "users.csv").write_text(users)
    (tmp_path / "courses.csv").write_text(courses)
    (tmp_path / "enrollments.csv").write_text(enrollments)
    return tmp_path


class TestCSVConnectorCanonical:
    async def test_authenticate_true_when_files_present(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        assert await conn.authenticate() is True

    async def test_authenticate_false_when_files_missing(self, tmp_path):
        conn = CSVConnector(tmp_path)
        assert await conn.authenticate() is False

    async def test_get_users(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        users = await conn.get_users()
        assert len(users) == 3
        alice = users[0]
        assert alice.id == "u1"
        assert alice.email == "alice@example.com"
        assert alice.hire_date.isoformat() == "2024-01-15"
        assert alice.employment_status == EmploymentStatus.ACTIVE

    async def test_get_users_filters(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        eng = await conn.get_users(filters={"department": "Engineering"})
        assert {u.id for u in eng} == {"u1", "u3"}
        terminated = await conn.get_users(filters={"employment_status": "terminated"})
        assert [u.id for u in terminated] == ["u3"]
        mx = await conn.get_users(filters={"region": "MX"})
        assert [u.id for u in mx] == ["u2"]

    async def test_get_courses(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        courses = await conn.get_courses()
        assert len(courses) == 2
        assert courses[0].mandatory is True
        mandatory = await conn.get_courses(filters={"mandatory": True})
        assert [c.id for c in mandatory] == ["c1"]

    async def test_get_enrollments(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        enrollments = await conn.get_enrollments()
        assert len(enrollments) == 2
        assert enrollments[0].status == EnrollmentStatus.COMPLETED
        assert enrollments[0].due_date.isoformat() == "2025-01-01"
        for_u2 = await conn.get_enrollments(user_ids=["u2"])
        assert [e.id for e in for_u2] == ["e2"]
        for_c1 = await conn.get_enrollments(course_ids=["c1"])
        assert len(for_c1) == 2

    async def test_trigger_reminder_unsupported(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        assert await conn.trigger_reminder("u1", "c1") is False


class TestCSVConnectorAliases:
    async def test_aliased_headers_map_to_canonical_fields(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path, ALIASED_USERS, ALIASED_COURSES, ALIASED_ENROLLMENTS))
        users = await conn.get_users()
        assert len(users) == 1
        assert users[0].employee_id == "E001"
        assert users[0].first_name == "Alice"
        assert users[0].last_name == "Smith"
        assert users[0].hire_date.isoformat() == "2024-01-15"

        courses = await conn.get_courses()
        assert courses[0].code == "SEC-101"
        assert courses[0].title == "Security Basics"
        assert courses[0].mandatory is True

        enrollments = await conn.get_enrollments()
        assert enrollments[0].status == EnrollmentStatus.COMPLETED
        assert enrollments[0].completion_percentage == 100.0
        assert enrollments[0].due_date.isoformat() == "2025-01-01"


class TestCSVConnectorRobustness:
    async def test_skips_rows_missing_required_fields(self, tmp_path):
        users = (
            "id,email,hire_date\n"
            "u1,alice@example.com,2024-01-15\n"
            ",missing-id@example.com,2024-01-15\n"
            "u3,,2024-01-15\n"
            "u4,bad-date@example.com,not-a-date\n"
        )
        conn = CSVConnector(write_csv_dir(
            tmp_path, users, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        loaded = await conn.get_users()
        assert [u.id for u in loaded] == ["u1"]
        assert conn.skipped_rows["users.csv"] == 3

    async def test_unknown_status_defaults(self, tmp_path):
        enrollments = (
            "user_id,course_id,status\n"
            "u1,c1,某种奇怪状态\n"
        )
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, enrollments))
        loaded = await conn.get_enrollments()
        assert loaded[0].status == EnrollmentStatus.NOT_STARTED
        assert loaded[0].id == "csv-0"

    async def test_bom_and_whitespace_tolerated(self, tmp_path):
        users = "﻿id, email ,hire_date\nu1, alice@example.com ,2024-01-15\n"
        conn = CSVConnector(write_csv_dir(
            tmp_path, users, CANONICAL_COURSES, CANONICAL_ENROLLMENTS))
        loaded = await conn.get_users()
        assert loaded[0].email == "alice@example.com"


class TestCSVLearningRecords:
    async def test_get_learning_records_reads_extended_columns(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path,
            LEARNING_RECORD_USERS,
            LEARNING_RECORD_COURSES,
            LEARNING_RECORD_ENROLLMENTS,
        ))

        records = await conn.get_learning_records()

        assert len(records) == 1
        record = records[0]
        assert record.id == "lr1"
        assert record.user_id == "u1"
        assert record.course_id == "c1"
        assert record.source_system == "canvas"
        assert record.source_record_id == "canvas-submission-1"
        assert record.status == LearningRecordStatus.COMPLETED
        assert record.completed_date is not None
        assert record.expires_at is not None
        assert record.expires_at.isoformat() == "2027-01-20"
        assert record.score == 98.0
        assert record.raw_source_hash is not None
        assert record.source_payload["Source System"] == "canvas"

    async def test_get_learning_records_filters_user_and_course(self, tmp_path):
        conn = CSVConnector(write_csv_dir(
            tmp_path,
            LEARNING_RECORD_USERS,
            LEARNING_RECORD_COURSES,
            LEARNING_RECORD_ENROLLMENTS,
        ))

        assert [r.id for r in await conn.get_learning_records(user_ids=["u1"])] == ["lr1"]
        assert await conn.get_learning_records(user_ids=["missing"]) == []
        assert [r.id for r in await conn.get_learning_records(course_ids=["c1"])] == ["lr1"]
        assert await conn.get_learning_records(course_ids=["missing"]) == []

    async def test_get_learning_records_preserves_extra_columns_with_string_keys(self, tmp_path):
        overwide_enrollments = (
            "Learning Record ID,Learner ID,Course ID,Completion Status\n"
            "lr1,u1,c1,Complete,unexpected-note,unexpected-source\n"
        )
        conn = CSVConnector(write_csv_dir(
            tmp_path,
            LEARNING_RECORD_USERS,
            LEARNING_RECORD_COURSES,
            overwide_enrollments,
        ))

        records = await conn.get_learning_records()

        assert len(records) == 1
        record = records[0]
        assert record.raw_source_hash is not None
        assert all(isinstance(key, str) for key in record.source_payload)
        assert record.source_payload["__extra_columns__"] == [
            "unexpected-note",
            "unexpected-source",
        ]


class TestCSVExpiryHandling:
    async def test_get_enrollments_marks_completed_past_expiry_overdue(self, tmp_path):
        enrollments = (
            "id,user_id,course_id,status,completed_date,expires_at,completion_percentage\n"
            "e-expired,u1,c1,completed,1999-01-01,2000-01-01,100\n"
        )
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, enrollments
        ))

        loaded = await conn.get_enrollments()

        assert loaded[0].status == EnrollmentStatus.OVERDUE

    async def test_get_learning_records_marks_completed_past_expiry_expired(self, tmp_path):
        enrollments = (
            "id,user_id,course_id,status,completed_date,expires_at,completion_percentage\n"
            "lr-expired,u1,c1,completed,1999-01-01,2000-01-01,100\n"
        )
        conn = CSVConnector(write_csv_dir(
            tmp_path, CANONICAL_USERS, CANONICAL_COURSES, enrollments
        ))

        loaded = await conn.get_learning_records()

        assert loaded[0].status == LearningRecordStatus.EXPIRED
        assert loaded[0].is_compliant is False
