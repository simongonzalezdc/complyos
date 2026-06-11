# ComplyOS Connectivity Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared connectivity foundation for one ComplyOS core with Workforce and Campus tracks.

**Architecture:** Add a broader `LearningRecord` domain model while keeping existing `Enrollment` compatibility. Add connector capability metadata and profile-aware CLI surfaces so ComplyOS can describe Workforce/Campus connector priorities before implementing every certified LMS adapter.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, Typer, Rich, pytest, FastMCP-compatible connector contracts.

---

## Scope check

The approved spec covers multiple phases. This plan implements the first working slice of the spec:

- `LearningRecord` abstraction.
- SQLite persistence for learning records.
- CSV/import support for source metadata, expiry, and evidence hashes.
- Workforce/Campus profile definitions.
- Connector capability matrix.
- CLI docs surfaces for profiles and connectors.
- Domain docs that keep Phase 4 operator readiness separate from Phase 5 major LMS connectivity.

This plan does not build production-certified Cornerstone, SAP SuccessFactors, Canvas, or D2L adapters. It creates the normalized contracts and operator-facing roadmap needed to add those adapters without forking the product.

## File structure

- Modify: `complyos/models/domain.py` — add `LearningRecordStatus` and `LearningRecord` with conversion helpers.
- Modify: `complyos/models/database.py` — add `DBLearningRecord` table.
- Modify: `complyos/core/repository.py` — add save/list/sync methods for learning records.
- Modify: `complyos/connectors/base.py` — add default `get_learning_records()` compatibility method.
- Modify: `complyos/connectors/csv_file.py` — parse extended learning-record columns from CSV exports.
- Create: `complyos/profiles.py` — central Workforce/Campus profile definitions.
- Create: `complyos/connectors/capabilities.py` — connector capability matrix.
- Modify: `complyos/cli.py` — add `init` and `connectors` commands.
- Create: `CONTEXT.md` — domain glossary for shared core, Workforce, Campus, and ambiguous terms.
- Modify: `README.md`, `ARCHITECTURE.md`, `llms.txt` — reference profiles, LearningRecord, and connector matrix.
- Add tests under `tests/unit/` for every new unit and CLI surface.

---

### Task 1: Add the LearningRecord domain model

**Files:**
- Modify: `complyos/models/domain.py`
- Test: `tests/unit/test_learning_record.py`

- [ ] **Step 1: Write failing tests for LearningRecord behavior**

Create `tests/unit/test_learning_record.py`:

```python
"""Tests for cross-LMS LearningRecord domain model."""

from __future__ import annotations

from datetime import date, datetime

from complyos.models.domain import Enrollment, EnrollmentStatus, LearningRecord, LearningRecordStatus


def test_learning_record_defaults_to_assigned():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="canvas",
        source_record_id="canvas-123",
    )

    assert record.status == LearningRecordStatus.ASSIGNED
    assert record.completion_percentage == 0.0
    assert record.is_compliant is False


def test_completed_learning_record_is_compliant():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="cornerstone",
        status=LearningRecordStatus.COMPLETED,
        completed_date=datetime(2026, 1, 15, 9, 30),
        completion_percentage=100,
        raw_source_hash="abc123",
    )

    assert record.is_compliant is True
    assert record.raw_source_hash == "abc123"


def test_exempt_learning_record_is_compliant():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="workday",
        status=LearningRecordStatus.EXEMPT,
        exempt=True,
    )

    assert record.is_compliant is True


def test_learning_record_from_enrollment_preserves_existing_fields():
    enrollment = Enrollment(
        id="e1",
        user_id="u1",
        course_id="c1",
        status=EnrollmentStatus.IN_PROGRESS,
        assigned_date=datetime(2026, 1, 1, 8, 0),
        due_date=date(2026, 2, 1),
        completion_percentage=50,
        score=87.5,
    )

    record = LearningRecord.from_enrollment(enrollment, source_system="legacy")

    assert record.id == "e1"
    assert record.user_id == "u1"
    assert record.course_id == "c1"
    assert record.source_system == "legacy"
    assert record.status == LearningRecordStatus.IN_PROGRESS
    assert record.due_date == date(2026, 2, 1)
    assert record.score == 87.5


def test_learning_record_to_enrollment_is_backward_compatible():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="docebo",
        status=LearningRecordStatus.EXPIRED,
        assigned_date=datetime(2026, 1, 1, 8, 0),
        due_date=date(2026, 2, 1),
        completed_date=datetime(2026, 1, 20, 8, 0),
        completion_percentage=100,
        score=91.0,
        expires_at=date(2027, 1, 20),
    )

    enrollment = record.to_enrollment()

    assert enrollment.id == "lr1"
    assert enrollment.user_id == "u1"
    assert enrollment.course_id == "c1"
    assert enrollment.status == EnrollmentStatus.OVERDUE
    assert enrollment.completed_date == datetime(2026, 1, 20, 8, 0)
    assert enrollment.completion_percentage == 100
    assert enrollment.score == 91.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_learning_record.py -q
```

Expected: FAIL because `LearningRecord` and `LearningRecordStatus` do not exist.

- [ ] **Step 3: Add LearningRecordStatus and LearningRecord**

Modify `complyos/models/domain.py` after `Enrollment`:

```python
class LearningRecordStatus(StrEnum):
    ASSIGNED = "assigned"
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    EXEMPT = "exempt"
    EXPIRED = "expired"


_LEARNING_TO_ENROLLMENT_STATUS: dict[LearningRecordStatus, EnrollmentStatus] = {
    LearningRecordStatus.ASSIGNED: EnrollmentStatus.NOT_STARTED,
    LearningRecordStatus.NOT_STARTED: EnrollmentStatus.NOT_STARTED,
    LearningRecordStatus.IN_PROGRESS: EnrollmentStatus.IN_PROGRESS,
    LearningRecordStatus.COMPLETED: EnrollmentStatus.COMPLETED,
    LearningRecordStatus.OVERDUE: EnrollmentStatus.OVERDUE,
    LearningRecordStatus.EXEMPT: EnrollmentStatus.EXEMPT,
    LearningRecordStatus.EXPIRED: EnrollmentStatus.OVERDUE,
}

_ENROLLMENT_TO_LEARNING_STATUS: dict[EnrollmentStatus, LearningRecordStatus] = {
    EnrollmentStatus.NOT_STARTED: LearningRecordStatus.NOT_STARTED,
    EnrollmentStatus.IN_PROGRESS: LearningRecordStatus.IN_PROGRESS,
    EnrollmentStatus.COMPLETED: LearningRecordStatus.COMPLETED,
    EnrollmentStatus.OVERDUE: LearningRecordStatus.OVERDUE,
    EnrollmentStatus.EXEMPT: LearningRecordStatus.EXEMPT,
}


class LearningRecord(BaseModel):
    """Normalized cross-LMS record of a learner's relationship to a learning item."""

    id: str
    user_id: str
    course_id: str
    source_system: str
    source_record_id: str | None = None
    status: LearningRecordStatus = LearningRecordStatus.ASSIGNED
    assigned_date: datetime | None = None
    due_date: date | None = None
    completed_date: datetime | None = None
    completion_percentage: float = 0.0
    score: float | None = None
    exempt: bool = False
    expires_at: date | None = None
    raw_source_hash: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_compliant(self) -> bool:
        return self.exempt or self.status in {
            LearningRecordStatus.COMPLETED,
            LearningRecordStatus.EXEMPT,
        }

    @classmethod
    def from_enrollment(
        cls,
        enrollment: Enrollment,
        *,
        source_system: str = "legacy",
        source_record_id: str | None = None,
        raw_source_hash: str | None = None,
    ) -> LearningRecord:
        return cls(
            id=enrollment.id,
            user_id=enrollment.user_id,
            course_id=enrollment.course_id,
            source_system=source_system,
            source_record_id=source_record_id,
            status=_ENROLLMENT_TO_LEARNING_STATUS[enrollment.status],
            assigned_date=enrollment.assigned_date,
            due_date=enrollment.due_date,
            completed_date=enrollment.completed_date,
            completion_percentage=enrollment.completion_percentage,
            score=enrollment.score,
            exempt=enrollment.status == EnrollmentStatus.EXEMPT,
            raw_source_hash=raw_source_hash,
        )

    def to_enrollment(self) -> Enrollment:
        return Enrollment(
            id=self.id,
            user_id=self.user_id,
            course_id=self.course_id,
            status=_LEARNING_TO_ENROLLMENT_STATUS[self.status],
            assigned_date=self.assigned_date,
            due_date=self.due_date,
            completed_date=self.completed_date,
            completion_percentage=self.completion_percentage,
            score=self.score,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/test_learning_record.py -q
```

Expected: PASS.

- [ ] **Step 5: Run model-related tests**

Run:

```bash
uv run pytest tests/unit/test_learning_record.py tests/unit/test_auditor.py tests/unit/test_csv_connector.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add complyos/models/domain.py tests/unit/test_learning_record.py
git commit -m "feat: add learning record domain model"
```

---

### Task 2: Persist LearningRecord in SQLite

**Files:**
- Modify: `complyos/models/database.py`
- Modify: `complyos/core/repository.py`
- Test: `tests/unit/test_database.py`
- Test: `tests/unit/test_repository.py`

- [ ] **Step 1: Add failing database table test**

Append to `tests/unit/test_database.py`:

```python
class TestDBLearningRecord:
    def test_create_learning_record(self, tmp_path):
        from complyos.models.database import DBLearningRecord

        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        user = DBUser(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 15),
        )
        course = DBCourse(id="c1", code="SEC-101", title="Security", mandatory=True)
        session.add_all([user, course])
        session.commit()

        record = DBLearningRecord(
            id="lr1",
            user_id="u1",
            course_id="c1",
            source_system="canvas",
            source_record_id="canvas-123",
            status="completed",
            assigned_date=datetime(2026, 1, 1, 8, 0),
            due_date=date(2026, 2, 1),
            completed_date=datetime(2026, 1, 20, 8, 0),
            completion_percentage=100.0,
            score=95.0,
            exempt=False,
            expires_at=date(2027, 1, 20),
            raw_source_hash="abc123",
            source_payload={"source": "fixture"},
        )
        session.add(record)
        session.commit()

        retrieved = session.query(DBLearningRecord).filter_by(id="lr1").first()
        assert retrieved is not None
        assert retrieved.source_system == "canvas"
        assert retrieved.source_record_id == "canvas-123"
        assert retrieved.expires_at == date(2027, 1, 20)
        assert retrieved.source_payload == {"source": "fixture"}
        session.close()
```

- [ ] **Step 2: Add failing repository tests**

Append to `tests/unit/test_repository.py`:

```python
class TestLearningRecordRepository:
    def test_save_and_list_learning_records(self, tmp_path):
        from complyos.models.domain import LearningRecord, LearningRecordStatus

        repo = LocalRepository(str(tmp_path / "test.db"))
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))

        record = LearningRecord(
            id="lr1",
            user_id="u1",
            course_id="c1",
            source_system="cornerstone",
            source_record_id="csod-1",
            status=LearningRecordStatus.COMPLETED,
            completed_date=datetime(2026, 1, 20, 8, 0),
            completion_percentage=100,
            score=88.0,
            expires_at=date(2027, 1, 20),
            raw_source_hash="hash-1",
            source_payload={"transcript_id": "csod-1"},
        )

        repo.save_learning_record(record)

        loaded = repo.list_learning_records(user_id="u1")
        assert len(loaded) == 1
        assert loaded[0].source_system == "cornerstone"
        assert loaded[0].source_record_id == "csod-1"
        assert loaded[0].status == LearningRecordStatus.COMPLETED
        assert loaded[0].expires_at == date(2027, 1, 20)
        assert loaded[0].raw_source_hash == "hash-1"
        assert loaded[0].source_payload == {"transcript_id": "csod-1"}

    def test_sync_learning_records(self, tmp_path):
        from complyos.models.domain import LearningRecord, LearningRecordStatus

        repo = LocalRepository(str(tmp_path / "test.db"))
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))

        records = [
            LearningRecord(
                id="lr1",
                user_id="u1",
                course_id="c1",
                source_system="canvas",
                status=LearningRecordStatus.IN_PROGRESS,
            )
        ]

        assert repo.sync_learning_records(records) == 1
        assert len(repo.list_learning_records(source_system="canvas")) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_database.py::TestDBLearningRecord tests/unit/test_repository.py::TestLearningRecordRepository -q
```

Expected: FAIL because `DBLearningRecord`, `save_learning_record`, `list_learning_records`, and `sync_learning_records` do not exist.

- [ ] **Step 4: Add DBLearningRecord**

Modify `complyos/models/database.py` after `DBEnrollment`:

```python
class DBLearningRecord(Base):
    __tablename__ = "learning_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    assigned_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    exempt: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    raw_source_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
```

- [ ] **Step 5: Add repository methods**

Modify imports in `complyos/core/repository.py`:

```python
from complyos.models.database import (
    DBAuditSnapshot,
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBLearningRecord,
    DBUser,
    init_db,
)
from complyos.models.domain import Course, Enrollment, LearningRecord, User
```

Add after `list_enrollments()`:

```python
    # ------------------------------------------------------------------
    # Learning records
    # ------------------------------------------------------------------
    def save_learning_record(self, record: LearningRecord) -> None:
        with self._session() as session:
            db_record = session.get(DBLearningRecord, record.id)
            if db_record is None:
                db_record = DBLearningRecord(id=record.id)
                session.add(db_record)

            db_record.user_id = record.user_id
            db_record.course_id = record.course_id
            db_record.source_system = record.source_system
            db_record.source_record_id = record.source_record_id
            db_record.status = record.status.value
            db_record.assigned_date = record.assigned_date
            db_record.due_date = record.due_date
            db_record.completed_date = record.completed_date
            db_record.completion_percentage = record.completion_percentage or 0.0
            db_record.score = record.score
            db_record.exempt = record.exempt
            db_record.expires_at = record.expires_at
            db_record.raw_source_hash = record.raw_source_hash
            db_record.source_payload = record.source_payload
            session.commit()

    def list_learning_records(
        self,
        *,
        user_id: str | None = None,
        course_id: str | None = None,
        status: str | None = None,
        source_system: str | None = None,
    ) -> list[LearningRecord]:
        with self._session() as session:
            query = session.query(DBLearningRecord)
            if user_id:
                query = query.where(DBLearningRecord.user_id == user_id)
            if course_id:
                query = query.where(DBLearningRecord.course_id == course_id)
            if status:
                query = query.where(DBLearningRecord.status == status)
            if source_system:
                query = query.where(DBLearningRecord.source_system == source_system)
            return [self._to_learning_record(r) for r in query.all()]
```

Add after `sync_enrollments()`:

```python
    def sync_learning_records(self, records: list[LearningRecord]) -> int:
        for record in records:
            self.save_learning_record(record)
        return len(records)
```

Modify `clear_all()` so learning records are deleted before courses/users:

```python
    def clear_all(self) -> None:
        with self._session() as session:
            session.query(DBLearningRecord).delete()
            session.query(DBEnrollment).delete()
            session.query(DBCourse).delete()
            session.query(DBUser).delete()
            session.query(DBEvidenceLedger).delete()
            session.commit()
```

Add mapper after `_to_enrollment()`:

```python
    @staticmethod
    def _to_learning_record(db: DBLearningRecord) -> LearningRecord:
        from complyos.models.domain import LearningRecordStatus

        return LearningRecord(
            id=db.id,
            user_id=db.user_id,
            course_id=db.course_id,
            source_system=db.source_system,
            source_record_id=db.source_record_id,
            status=LearningRecordStatus(db.status),
            assigned_date=db.assigned_date,
            due_date=db.due_date,
            completed_date=db.completed_date,
            completion_percentage=db.completion_percentage,
            score=db.score,
            exempt=db.exempt,
            expires_at=db.expires_at,
            raw_source_hash=db.raw_source_hash,
            source_payload=db.source_payload or {},
        )
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_database.py::TestDBLearningRecord tests/unit/test_repository.py::TestLearningRecordRepository -q
```

Expected: PASS.

- [ ] **Step 7: Run persistence suite**

Run:

```bash
uv run pytest tests/unit/test_database.py tests/unit/test_repository.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add complyos/models/database.py complyos/core/repository.py tests/unit/test_database.py tests/unit/test_repository.py
git commit -m "feat: persist learning records"
```

---

### Task 3: Add connector-level learning-record compatibility

**Files:**
- Modify: `complyos/connectors/base.py`
- Modify: `complyos/connectors/csv_file.py`
- Test: `tests/unit/test_csv_connector.py`
- Test: `tests/unit/test_mock_connector.py`

- [ ] **Step 1: Add failing CSV learning-record tests**

Append to `tests/unit/test_csv_connector.py`:

```python
LEARNING_RECORD_USERS = """id,email,hire_date
u1,student@example.edu,2024-01-15
"""

LEARNING_RECORD_COURSES = """id,code,title,mandatory
c1,FERPA-101,FERPA Basics,true
"""

LEARNING_RECORD_ENROLLMENTS = """Learning Record ID,Learner ID,Course ID,Completion Status,Assigned Date,Due Date,Completed Date,Score,Expires At,Source System,Source Record ID
lr1,u1,c1,Complete,2026-01-01,2026-02-01,2026-01-20,98,2027-01-20,canvas,canvas-submission-1
"""


class TestCSVLearningRecords:
    async def test_get_learning_records_reads_extended_columns(self, tmp_path):
        conn = CSVConnector(
            write_csv_dir(
                tmp_path,
                LEARNING_RECORD_USERS,
                LEARNING_RECORD_COURSES,
                LEARNING_RECORD_ENROLLMENTS,
            )
        )

        records = await conn.get_learning_records()

        assert len(records) == 1
        record = records[0]
        assert record.id == "lr1"
        assert record.user_id == "u1"
        assert record.course_id == "c1"
        assert record.source_system == "canvas"
        assert record.source_record_id == "canvas-submission-1"
        assert record.status.value == "completed"
        assert record.completed_date is not None
        assert record.expires_at.isoformat() == "2027-01-20"
        assert record.score == 98.0
        assert record.raw_source_hash is not None
        assert record.source_payload["Source System"] == "canvas"

    async def test_get_learning_records_filters_user_and_course(self, tmp_path):
        conn = CSVConnector(
            write_csv_dir(
                tmp_path,
                LEARNING_RECORD_USERS,
                LEARNING_RECORD_COURSES,
                LEARNING_RECORD_ENROLLMENTS,
            )
        )

        assert len(await conn.get_learning_records(user_ids=["u1"])) == 1
        assert len(await conn.get_learning_records(user_ids=["missing"])) == 0
        assert len(await conn.get_learning_records(course_ids=["c1"])) == 1
        assert len(await conn.get_learning_records(course_ids=["missing"])) == 0
```

- [ ] **Step 2: Add failing base-connector compatibility test**

Append to `tests/unit/test_mock_connector.py`:

```python
async def test_default_get_learning_records_maps_enrollments():
    from complyos.connectors.mock import MockConnector

    conn = MockConnector()
    records = await conn.get_learning_records()

    assert records
    assert {record.source_system for record in records} == {"mock"}
    assert {record.id for record in records} == {enrollment.id for enrollment in await conn.get_enrollments()}
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_csv_connector.py::TestCSVLearningRecords tests/unit/test_mock_connector.py::test_default_get_learning_records_maps_enrollments -q
```

Expected: FAIL because `get_learning_records()` is not available.

- [ ] **Step 4: Add base connector default method**

Modify `complyos/connectors/base.py` imports:

```python
from complyos.models.domain import Course, Enrollment, LearningRecord, User
```

Add this method after `get_enrollments()` and before `trigger_reminder()`:

```python
    async def get_learning_records(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[LearningRecord]:
        """Fetch normalized cross-LMS learning records.

        Existing connectors can keep implementing get_enrollments(); this compatibility
        method maps those enrollments to LearningRecord until a connector has richer
        transcript/completion metadata available.
        """
        enrollments = await self.get_enrollments(user_ids=user_ids, course_ids=course_ids)
        return [
            LearningRecord.from_enrollment(
                enrollment,
                source_system=self.name,
                source_record_id=enrollment.id,
            )
            for enrollment in enrollments
        ]
```

- [ ] **Step 5: Extend CSV aliases and parsing**

Modify `complyos/connectors/csv_file.py` imports:

```python
import csv
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.models.domain import (
    Course,
    EmploymentStatus,
    Enrollment,
    EnrollmentStatus,
    LearningRecord,
    LearningRecordStatus,
    User,
)
```

Extend `ENROLLMENT_ALIASES`:

```python
ENROLLMENT_ALIASES: dict[str, list[str]] = {
    "id": ["id", "enrollmentid", "registrationid", "learningrecordid", "transcriptid"],
    "user_id": ["userid", "user", "learnerid", "studentid"],
    "course_id": ["courseid", "course", "learningitemid"],
    "status": ["status", "enrollmentstatus", "completionstatus"],
    "assigned_date": ["assigneddate", "enrolldate", "enrollmentdate", "registrationdate"],
    "due_date": ["duedate", "deadline", "targetdate"],
    "completed_date": ["completeddate", "completiondate", "finisheddate"],
    "completion_percentage": ["completionpercentage", "progress", "percentcomplete"],
    "score": ["score", "grade", "finalscore"],
    "expires_at": ["expiresat", "expirationdate", "expirydate", "recertificationdate"],
    "source_system": ["sourcesystem", "system", "platform", "lms"],
    "source_record_id": ["sourcerecordid", "externalid", "transcriptitemid"],
    "exempt": ["exempt", "waived", "exception"],
}
```

Add after `_parse_float()`:

```python
def _hash_row(row: dict[str, str]) -> str:
    raw_json = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(raw_json.encode()).hexdigest()


def _to_learning_status(status: EnrollmentStatus) -> LearningRecordStatus:
    return {
        EnrollmentStatus.NOT_STARTED: LearningRecordStatus.NOT_STARTED,
        EnrollmentStatus.IN_PROGRESS: LearningRecordStatus.IN_PROGRESS,
        EnrollmentStatus.COMPLETED: LearningRecordStatus.COMPLETED,
        EnrollmentStatus.OVERDUE: LearningRecordStatus.OVERDUE,
        EnrollmentStatus.EXEMPT: LearningRecordStatus.EXEMPT,
    }[status]
```

Add `self._learning_records` to `CSVConnector.__init__`:

```python
        self._learning_records: list[LearningRecord] | None = None
```

Add method after `_load_enrollments()`:

```python
    def _load_learning_records(self) -> list[LearningRecord]:
        if self._learning_records is None:
            self._learning_records = []
            for i, row in enumerate(self._read_rows(ENROLLMENTS_FILE)):
                mapped = _remap_row(row, ENROLLMENT_ALIASES)
                if "user_id" not in mapped or "course_id" not in mapped:
                    self.skipped_rows[ENROLLMENTS_FILE] += 1
                    continue
                raw_status = mapped.get("status", "not_started").lower().replace(" ", "_")
                enrollment_status = STATUS_SYNONYMS.get(raw_status, EnrollmentStatus.NOT_STARTED)
                record_id = mapped.get("id", f"csv-{i}")
                source_system = mapped.get("source_system", self.name)
                exempt = mapped.get("exempt", "").lower() in TRUTHY or enrollment_status == EnrollmentStatus.EXEMPT
                self._learning_records.append(
                    LearningRecord(
                        id=record_id,
                        user_id=mapped["user_id"],
                        course_id=mapped["course_id"],
                        source_system=source_system,
                        source_record_id=mapped.get("source_record_id", record_id),
                        status=_to_learning_status(enrollment_status),
                        assigned_date=_parse_datetime(mapped.get("assigned_date")),
                        due_date=_parse_date(mapped.get("due_date")),
                        completed_date=_parse_datetime(mapped.get("completed_date")),
                        completion_percentage=_parse_float(mapped.get("completion_percentage")) or 0.0,
                        score=_parse_float(mapped.get("score")),
                        exempt=exempt,
                        expires_at=_parse_date(mapped.get("expires_at")),
                        raw_source_hash=_hash_row(row),
                        source_payload=dict(row),
                    )
                )
        return self._learning_records
```

Add public method after `get_enrollments()`:

```python
    async def get_learning_records(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[LearningRecord]:
        result = self._load_learning_records()
        if user_ids:
            result = [r for r in result if r.user_id in user_ids]
        if course_ids:
            result = [r for r in result if r.course_id in course_ids]
        return result
```

- [ ] **Step 6: Run focused connector tests**

Run:

```bash
uv run pytest tests/unit/test_csv_connector.py::TestCSVLearningRecords tests/unit/test_mock_connector.py::test_default_get_learning_records_maps_enrollments -q
```

Expected: PASS.

- [ ] **Step 7: Run full connector tests**

Run:

```bash
uv run pytest tests/unit/test_csv_connector.py tests/unit/test_mock_connector.py tests/unit/test_workday_connector.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add complyos/connectors/base.py complyos/connectors/csv_file.py tests/unit/test_csv_connector.py tests/unit/test_mock_connector.py
git commit -m "feat: expose learning records from connectors"
```

---

### Task 4: Add Workforce/Campus profiles

**Files:**
- Create: `complyos/profiles.py`
- Modify: `complyos/cli.py`
- Test: `tests/unit/test_profiles.py`
- Test: `tests/unit/test_cli_profiles.py`

- [ ] **Step 1: Write failing profile unit tests**

Create `tests/unit/test_profiles.py`:

```python
"""Tests for ComplyOS market profiles."""

from __future__ import annotations

import pytest

from complyos.profiles import ComplyOSProfile, get_profile, list_profiles, render_profile_config


def test_list_profiles_contains_workforce_and_campus():
    profiles = list_profiles()
    assert [profile.name for profile in profiles] == ["workforce", "campus"]


def test_workforce_profile_terms():
    profile = get_profile("workforce")
    assert profile.display_name == "ComplyOS Workforce"
    assert profile.learner_term == "employee"
    assert profile.learning_item_term == "training"
    assert "cornerstone" in profile.recommended_connectors


def test_campus_profile_terms():
    profile = get_profile(ComplyOSProfile.CAMPUS)
    assert profile.display_name == "ComplyOS Campus"
    assert profile.learner_term == "student"
    assert profile.learning_item_term == "course"
    assert "canvas" in profile.recommended_connectors


def test_unknown_profile_raises_value_error():
    with pytest.raises(ValueError, match="Unknown ComplyOS profile"):
        get_profile("unknown")


def test_render_profile_config_contains_profile_and_connector():
    text = render_profile_config("campus")
    assert "profile: campus" in text
    assert "connector:" in text
    assert "type: csv" in text
    assert "learner_term: student" in text
```

- [ ] **Step 2: Write failing CLI tests**

Create `tests/unit/test_cli_profiles.py`:

```python
"""CLI tests for profile initialization."""

from __future__ import annotations

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_init_writes_workforce_config(tmp_path):
    output = tmp_path / "complyos.yaml"
    result = runner.invoke(app, ["init", "--profile", "workforce", "--output", str(output)])

    assert result.exit_code == 0
    assert "Initialized ComplyOS Workforce" in result.output
    assert output.exists()
    text = output.read_text()
    assert "profile: workforce" in text
    assert "learner_term: employee" in text


def test_init_writes_campus_config(tmp_path):
    output = tmp_path / "campus.yaml"
    result = runner.invoke(app, ["init", "--profile", "campus", "--output", str(output)])

    assert result.exit_code == 0
    assert "Initialized ComplyOS Campus" in result.output
    text = output.read_text()
    assert "profile: campus" in text
    assert "learner_term: student" in text


def test_init_rejects_unknown_profile(tmp_path):
    output = tmp_path / "bad.yaml"
    result = runner.invoke(app, ["init", "--profile", "unknown", "--output", str(output)])

    assert result.exit_code == 1
    assert "Unknown ComplyOS profile" in result.output
    assert not output.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_profiles.py tests/unit/test_cli_profiles.py -q
```

Expected: FAIL because `complyos.profiles` and `complyos init` do not exist.

- [ ] **Step 4: Create profile definitions**

Create `complyos/profiles.py`:

```python
"""Market profile definitions for ComplyOS Workforce and Campus."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ComplyOSProfile(StrEnum):
    WORKFORCE = "workforce"
    CAMPUS = "campus"


@dataclass(frozen=True)
class ProfileDefinition:
    name: str
    display_name: str
    buyer_terms: tuple[str, ...]
    learner_term: str
    learning_item_term: str
    responsible_party_term: str
    record_term: str
    gap_term: str
    recommended_connectors: tuple[str, ...]


_PROFILE_DEFINITIONS: dict[ComplyOSProfile, ProfileDefinition] = {
    ComplyOSProfile.WORKFORCE: ProfileDefinition(
        name="workforce",
        display_name="ComplyOS Workforce",
        buyer_terms=("L&D", "People Ops", "HRIS", "Security Compliance"),
        learner_term="employee",
        learning_item_term="training",
        responsible_party_term="manager",
        record_term="transcript",
        gap_term="compliance gap",
        recommended_connectors=(
            "csv",
            "workday",
            "cornerstone",
            "successfactors",
            "docebo",
            "absorb",
            "litmos",
            "learnupon",
            "talentlms",
            "oracle-learning-cloud",
        ),
    ),
    ComplyOSProfile.CAMPUS: ProfileDefinition(
        name="campus",
        display_name="ComplyOS Campus",
        buyer_terms=("Academic Technology", "Higher-Ed IT", "Program Compliance", "District IT"),
        learner_term="student",
        learning_item_term="course",
        responsible_party_term="advisor",
        record_term="enrollment",
        gap_term="missing requirement",
        recommended_connectors=(
            "csv",
            "canvas",
            "brightspace",
            "blackboard",
            "moodle",
            "schoology",
            "google-classroom",
        ),
    ),
}


def get_profile(profile: str | ComplyOSProfile) -> ProfileDefinition:
    try:
        key = profile if isinstance(profile, ComplyOSProfile) else ComplyOSProfile(profile)
    except ValueError as exc:
        valid = ", ".join(p.value for p in ComplyOSProfile)
        raise ValueError(f"Unknown ComplyOS profile '{profile}'. Valid profiles: {valid}") from exc
    return _PROFILE_DEFINITIONS[key]


def list_profiles() -> list[ProfileDefinition]:
    return [_PROFILE_DEFINITIONS[ComplyOSProfile.WORKFORCE], _PROFILE_DEFINITIONS[ComplyOSProfile.CAMPUS]]


def render_profile_config(profile: str | ComplyOSProfile) -> str:
    definition = get_profile(profile)
    connectors = "\n".join(f"    - {connector}" for connector in definition.recommended_connectors)
    buyers = "\n".join(f"    - {buyer}" for buyer in definition.buyer_terms)
    return f"""# ComplyOS configuration generated for {definition.display_name}
profile: {definition.name}

connector:
  type: csv
  csv_dir: ./examples/csv

database:
  path: complyos.db

defaults:
  learner_term: {definition.learner_term}
  learning_item_term: {definition.learning_item_term}
  responsible_party_term: {definition.responsible_party_term}
  record_term: {definition.record_term}
  gap_term: {definition.gap_term}

recommended_connectors:
{connectors}

buyer_terms:
{buyers}
"""
```

- [ ] **Step 5: Add CLI init command**

Modify `complyos/cli.py` imports:

```python
from pathlib import Path
```

Add after `health()`:

```python
@app.command()
def init(
    profile: str = typer.Option("workforce", "--profile", help="Profile: workforce or campus"),
    output: str = typer.Option("complyos.yaml", "--output", help="Config file to write"),
):
    """Create a starter ComplyOS config for a market profile."""
    from complyos.profiles import get_profile, render_profile_config

    try:
        definition = get_profile(profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    path = Path(output)
    path.write_text(render_profile_config(definition.name))
    console.print(f"[green]Initialized {definition.display_name} config at {path}[/green]")
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_profiles.py tests/unit/test_cli_profiles.py -q
```

Expected: PASS.

- [ ] **Step 7: Run CLI tests**

Run:

```bash
uv run pytest tests/unit/test_cli.py tests/unit/test_cli_profiles.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add complyos/profiles.py complyos/cli.py tests/unit/test_profiles.py tests/unit/test_cli_profiles.py
git commit -m "feat: add workforce and campus profiles"
```

---

### Task 5: Add connector capability matrix

**Files:**
- Create: `complyos/connectors/capabilities.py`
- Modify: `complyos/cli.py`
- Test: `tests/unit/test_connector_capabilities.py`
- Test: `tests/unit/test_cli_connectors.py`

- [ ] **Step 1: Write failing capability tests**

Create `tests/unit/test_connector_capabilities.py`:

```python
"""Tests for LMS connector capability matrix."""

from __future__ import annotations

from complyos.connectors.capabilities import get_connector_capability, list_connector_capabilities


def test_matrix_contains_key_workforce_connectors():
    names = {item.name for item in list_connector_capabilities(profile="workforce")}
    assert {"csv", "workday", "cornerstone", "successfactors", "docebo", "absorb"}.issubset(names)


def test_matrix_contains_key_campus_connectors():
    names = {item.name for item in list_connector_capabilities(profile="campus")}
    assert {"csv", "canvas", "brightspace", "blackboard", "moodle"}.issubset(names)


def test_canvas_capabilities_include_learning_records_and_due_dates():
    canvas = get_connector_capability("canvas")
    assert canvas.profile == "campus"
    assert canvas.supports_learning_records is True
    assert canvas.supports_due_dates is True
    assert canvas.status == "planned"


def test_csv_is_supported_for_both_tracks():
    csv = get_connector_capability("csv")
    assert csv.profile == "both"
    assert csv.status == "supported"
    assert csv.supports_users is True
    assert csv.supports_courses is True
    assert csv.supports_learning_records is True
```

- [ ] **Step 2: Write failing CLI tests**

Create `tests/unit/test_cli_connectors.py`:

```python
"""CLI tests for connector matrix."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_connectors_table_lists_workforce_systems():
    result = runner.invoke(app, ["connectors", "--profile", "workforce"])

    assert result.exit_code == 0
    assert "cornerstone" in result.output
    assert "successfactors" in result.output
    assert "canvas" not in result.output


def test_connectors_json_lists_campus_systems():
    result = runner.invoke(app, ["connectors", "--profile", "campus", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    names = {item["name"] for item in data}
    assert "canvas" in names
    assert "brightspace" in names
    assert "cornerstone" not in names
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_connector_capabilities.py tests/unit/test_cli_connectors.py -q
```

Expected: FAIL because capability module and CLI command do not exist.

- [ ] **Step 4: Create capability matrix**

Create `complyos/connectors/capabilities.py`:

```python
"""Connector capability matrix for prioritized LMS systems."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ConnectorCapability:
    name: str
    display_name: str
    profile: str
    status: str
    auth: str
    supports_users: bool
    supports_courses: bool
    supports_assignments: bool
    supports_learning_records: bool
    supports_due_dates: bool
    supports_exemptions: bool
    supports_scores: bool
    supports_expiry: bool
    docs_url: str

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


_CAPABILITIES: tuple[ConnectorCapability, ...] = (
    ConnectorCapability("csv", "CSV export folder", "both", "supported", "none", True, True, True, True, True, True, True, True, "./examples/csv"),
    ConnectorCapability("workday", "Workday Learning", "workforce", "supported", "basic-auth", True, True, True, True, True, False, True, False, "https://community.workday.com/sites/default/files/file-hosting/restapi/"),
    ConnectorCapability("cornerstone", "Cornerstone OnDemand", "workforce", "planned", "oauth-or-api", True, True, True, True, True, True, True, True, "https://csod.dev/reference/learning/"),
    ConnectorCapability("successfactors", "SAP SuccessFactors Learning", "workforce", "planned", "oauth", True, True, True, True, True, True, True, True, "https://help.sap.com/docs/successfactors-learning/"),
    ConnectorCapability("docebo", "Docebo", "workforce", "planned", "oauth", True, True, True, True, True, True, True, True, "https://developer.docebo.com/docs/api-general-information"),
    ConnectorCapability("absorb", "Absorb LMS", "workforce", "planned", "api-key", True, True, True, True, True, True, True, True, "https://docs.myabsorb.com/"),
    ConnectorCapability("litmos", "Litmos", "workforce", "planned", "api-key", True, True, True, True, True, False, True, False, "https://www.litmos.com/learning-management-system/api"),
    ConnectorCapability("learnupon", "LearnUpon", "workforce", "planned", "api-key", True, True, True, True, True, False, True, False, "https://docs.learnupon.com/api/"),
    ConnectorCapability("talentlms", "TalentLMS", "workforce", "planned", "api-key", True, True, True, True, True, False, True, False, "https://help.talentlms.com/hc/en-us/articles/24874457011356-TalentLMS-API-V2"),
    ConnectorCapability("oracle-learning-cloud", "Oracle Learning Cloud", "workforce", "planned", "oauth", True, True, True, True, True, True, True, True, "https://docs.oracle.com/en/cloud/saas/human-resources/farws/api-learner-learning-records.html"),
    ConnectorCapability("canvas", "Canvas LMS", "campus", "planned", "access-token", True, True, True, True, True, True, True, False, "https://developerdocs.instructure.com/services/canvas/resources/enrollments"),
    ConnectorCapability("brightspace", "D2L Brightspace", "campus", "planned", "oauth", True, True, True, True, True, False, True, False, "https://docs.valence.desire2learn.com/reference.html"),
    ConnectorCapability("blackboard", "Anthology Blackboard Learn", "campus", "planned", "oauth", True, True, True, True, True, False, True, False, "https://developer.blackboard.com/portal/displayApi"),
    ConnectorCapability("moodle", "Moodle", "campus", "planned", "token", True, True, True, True, True, False, True, True, "https://docs.moodle.org/dev/Web_service_API_functions"),
    ConnectorCapability("schoology", "Schoology", "campus", "planned", "oauth", True, True, True, True, True, False, True, False, "https://developers.schoology.com/api-documentation/rest-api-v1/"),
    ConnectorCapability("google-classroom", "Google Classroom", "campus", "planned", "oauth", True, True, True, True, True, False, True, False, "https://developers.google.com/workspace/classroom/reference/rest"),
)


def list_connector_capabilities(profile: str | None = None) -> list[ConnectorCapability]:
    if profile is None or profile == "all":
        return list(_CAPABILITIES)
    return [item for item in _CAPABILITIES if item.profile in {profile, "both"}]


def get_connector_capability(name: str) -> ConnectorCapability:
    for item in _CAPABILITIES:
        if item.name == name:
            return item
    valid = ", ".join(item.name for item in _CAPABILITIES)
    raise ValueError(f"Unknown connector '{name}'. Valid connectors: {valid}")
```

- [ ] **Step 5: Add CLI connectors command**

Modify `complyos/cli.py` with this command after `init()`:

```python
@app.command()
def connectors(
    profile: str = typer.Option("all", "--profile", help="Filter: all, workforce, or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List LMS connector capabilities and roadmap status."""
    from complyos.connectors.capabilities import list_connector_capabilities

    items = list_connector_capabilities(profile=profile)

    if json_output:
        console.print(json.dumps([item.to_dict() for item in items], indent=2))
        return

    table = Table(title="ComplyOS Connector Matrix")
    table.add_column("Name")
    table.add_column("Profile")
    table.add_column("Status")
    table.add_column("Auth")
    table.add_column("Records")
    table.add_column("Due Dates")
    table.add_column("Expiry")
    for item in items:
        table.add_row(
            item.name,
            item.profile,
            item.status,
            item.auth,
            "yes" if item.supports_learning_records else "no",
            "yes" if item.supports_due_dates else "no",
            "yes" if item.supports_expiry else "no",
        )
    console.print(table)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_connector_capabilities.py tests/unit/test_cli_connectors.py -q
```

Expected: PASS.

- [ ] **Step 7: Run CLI suite**

Run:

```bash
uv run pytest tests/unit/test_cli.py tests/unit/test_cli_profiles.py tests/unit/test_cli_connectors.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add complyos/connectors/capabilities.py complyos/cli.py tests/unit/test_connector_capabilities.py tests/unit/test_cli_connectors.py
git commit -m "feat: add connector capability matrix"
```

---

### Task 6: Sync learning records during CLI sync

**Files:**
- Modify: `complyos/cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Add failing sync test for learning records**

Append to `TestSyncCommand` in `tests/unit/test_cli.py`:

```python
    def test_sync_persists_learning_records_when_connector_supports_them(self, monkeypatch, tmp_path):
        from complyos.models.domain import Course, LearningRecord, LearningRecordStatus, User

        class FakeConnector:
            name = "fake"

            async def authenticate(self):
                return True

            async def get_users(self):
                return [
                    User(
                        id="u1",
                        employee_id="E001",
                        email="a@example.com",
                        first_name="A",
                        last_name="A",
                        department="Eng",
                        region="US",
                        hire_date=date(2023, 1, 1),
                        employment_status="active",
                    )
                ]

            async def get_courses(self):
                return [Course(id="c1", code="SEC-101", title="Security")]

            async def get_enrollments(self):
                return []

            async def get_learning_records(self):
                return [
                    LearningRecord(
                        id="lr1",
                        user_id="u1",
                        course_id="c1",
                        source_system="fake",
                        status=LearningRecordStatus.COMPLETED,
                    )
                ]

        monkeypatch.setattr("complyos.cli._get_connector", lambda: FakeConnector())
        db_path = str(tmp_path / "sync.db")
        result = runner.invoke(app, ["sync", "--db", db_path])

        assert result.exit_code == 0
        assert "1 learning records" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_cli.py::TestSyncCommand::test_sync_persists_learning_records_when_connector_supports_them -q
```

Expected: FAIL because `sync` does not call `get_learning_records()` or print the count.

- [ ] **Step 3: Update sync command**

Modify `sync()` in `complyos/cli.py` so `_sync()` fetches and persists learning records:

```python
        users = await connector.get_users()
        courses = await connector.get_courses()
        enrollments = await connector.get_enrollments()
        learning_records = await connector.get_learning_records()

        repo.clear_all()
        repo.sync_users(users)
        repo.sync_courses(courses)
        repo.sync_enrollments(enrollments)
        repo.sync_learning_records(learning_records)

        return len(users), len(courses), len(enrollments), len(learning_records)
```

Modify the result unpacking and console message:

```python
    user_count, course_count, enrollment_count, learning_record_count = asyncio.run(_sync())
    console.print(
        f"[green]Synced {user_count} users, {course_count} courses, "
        f"{enrollment_count} enrollments, {learning_record_count} learning records[/green]"
    )
```

- [ ] **Step 4: Update existing sync test assertion**

In `tests/unit/test_cli.py::TestSyncCommand::test_sync_success`, change:

```python
assert "Synced 1 users, 1 courses, 0 enrollments" in result.output
```

To:

```python
assert "Synced 1 users, 1 courses, 0 enrollments, 0 learning records" in result.output
```

- [ ] **Step 5: Run sync tests**

Run:

```bash
uv run pytest tests/unit/test_cli.py::TestSyncCommand -q
```

Expected: PASS.

- [ ] **Step 6: Run CLI tests**

Run:

```bash
uv run pytest tests/unit/test_cli.py tests/unit/test_cli_profiles.py tests/unit/test_cli_connectors.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add complyos/cli.py tests/unit/test_cli.py
git commit -m "feat: sync learning records"
```

---

### Task 7: Update examples and docs

**Files:**
- Create: `CONTEXT.md`
- Create: `examples/csv-campus/users.csv`
- Create: `examples/csv-campus/courses.csv`
- Create: `examples/csv-campus/enrollments.csv`
- Create: `examples/csv-workforce/users.csv`
- Create: `examples/csv-workforce/courses.csv`
- Create: `examples/csv-workforce/enrollments.csv`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `llms.txt`

- [ ] **Step 1: Create domain glossary**

Create `CONTEXT.md`:

```md
# ComplyOS Domain Context

ComplyOS is a learning-compliance evidence engine that normalizes LMS data into one audit model while presenting Workforce and Campus tracks with market-specific language.

## Language

**Learner**:
A person who is expected to complete a learning item.
_Avoid_: Account, seat

**Learning Item**:
A training module, course, certification, or assignment that can be required for compliance.
_Avoid_: Content blob, asset

**Learning Record**:
A normalized source-system record linking a learner to a learning item with status, due date, completion, exemption, score, expiry, and source evidence.
_Avoid_: Enrollment when discussing cross-LMS connector contracts

**Enrollment**:
The legacy ComplyOS model for a user's relationship to a course, kept for compatibility with the current audit engine.
_Avoid_: Transcript item when the code path specifically uses `Enrollment`

**Compliance Gap**:
A missing, incomplete, overdue, expired, or non-exempt required learning item for a learner.
_Avoid_: Failure, violation

**Evidence Ledger**:
An immutable audit trail entry with hashes for raw connector data and processed audit output.
_Avoid_: Log, report

**Workforce**:
The corporate compliance track for employees, managers, L&D, HRIS, security, and regulatory training.
_Avoid_: Enterprise product fork

**Campus**:
The education compliance track for students, advisors, instructors, academic technology, and program compliance.
_Avoid_: Education product fork

## Relationships

- A **Learner** can have many **Learning Records**.
- A **Learning Item** can appear in many **Learning Records**.
- A **Learning Record** can be converted to one legacy **Enrollment** for current audit compatibility.
- A **Compliance Gap** is derived from required **Learning Items** and non-compliant **Learning Records** or **Enrollments**.
- An **Evidence Ledger** entry records how a compliance result was produced.
- **Workforce** and **Campus** share the same **Learning Record** model.

## Example dialogue

> **Dev:** "Should Canvas submissions and Cornerstone transcript items become different domain objects?"
> **Domain expert:** "No. They are both Learning Records once ComplyOS normalizes them. Campus can call it an enrollment in reports, and Workforce can call it a transcript item, but the audit engine should see the same concept."

## Flagged ambiguities

- "BSL" is ambiguous. Use **BUSL-1.1** for Business Source License 1.1; **BSL-1.0** usually means Boost Software License.
- "Enrollment" is too narrow for major LMS connectivity. Use **Learning Record** for cross-LMS connector contracts and keep **Enrollment** only for current compatibility paths.
- "Course" is acceptable in current code, but docs should use **Learning Item** when discussing cross-market Workforce and Campus behavior.
```

- [ ] **Step 2: Add Workforce sample CSV files**

Create `examples/csv-workforce/users.csv`:

```csv
id,employee_id,email,first_name,last_name,department,region,hire_date,employment_status,manager_id,job_title
u1,E001,alice@example.com,Alice,Smith,Engineering,US,2024-01-15,active,m1,Software Engineer
u2,E002,bob@example.com,Bob,Jones,Finance,US,2023-06-01,active,m2,Finance Manager
```

Create `examples/csv-workforce/courses.csv`:

```csv
id,code,title,mandatory,category
c1,SEC-101,Information Security Basics,true,Compliance
c2,COC-101,Code of Conduct,true,Compliance
```

Create `examples/csv-workforce/enrollments.csv`:

```csv
Learning Record ID,Learner ID,Course ID,Completion Status,Assigned Date,Due Date,Completed Date,Score,Expires At,Source System,Source Record ID
lr1,u1,c1,Complete,2026-01-01,2026-02-01,2026-01-20,98,2027-01-20,cornerstone,csod-transcript-1
lr2,u2,c1,In Progress,2026-01-01,2026-02-01,,45,,cornerstone,csod-transcript-2
```

- [ ] **Step 3: Add Campus sample CSV files**

Create `examples/csv-campus/users.csv`:

```csv
id,email,first_name,last_name,department,region,hire_date,employment_status
s1,student1@example.edu,Student,One,Nursing,US,2025-08-15,active
s2,student2@example.edu,Student,Two,Nursing,US,2025-08-15,active
```

Create `examples/csv-campus/courses.csv`:

```csv
id,code,title,mandatory,category
c1,FERPA-101,FERPA Basics,true,Compliance
c2,CLINICAL-201,Clinical Safety,true,Program Requirement
```

Create `examples/csv-campus/enrollments.csv`:

```csv
Learning Record ID,Learner ID,Course ID,Completion Status,Assigned Date,Due Date,Completed Date,Score,Source System,Source Record ID
lr1,s1,c1,Complete,2026-01-10,2026-02-10,2026-01-25,95,canvas,canvas-enrollment-1
lr2,s2,c1,Not Started,2026-01-10,2026-02-10,,,canvas,canvas-enrollment-2
```

- [ ] **Step 4: Update README commands and narrative**

Modify `README.md` Quick Start CLI block to include:

```bash
# Create a Workforce starter config
complyos init --profile workforce

# Create a Campus starter config
complyos init --profile campus --output campus.yaml

# See connector roadmap and capability coverage
complyos connectors --profile workforce
complyos connectors --profile campus --json
```

Modify the Domain Model section so it mentions `LearningRecord` before `ComplianceGap`:

```md
The cross-LMS connector contract normalizes transcripts, enrollments, assignments,
submissions, completions, exemptions, and recertifications into `LearningRecord`.
The existing `Enrollment` model remains for compatibility with the current audit
engine.
```

- [ ] **Step 5: Update ARCHITECTURE and llms docs**

In `ARCHITECTURE.md`, add `LearningRecord` to the Domain Model list:

```md
- **LearningRecord** — A normalized cross-LMS source record for assignment, completion, exemption, score, due date, and expiry data
```

In `llms.txt`, add these bullets:

```md
- `complyos/profiles.py` — Workforce/Campus profile definitions
- `complyos/connectors/capabilities.py` — LMS connector capability matrix
- `LearningRecord` is the cross-LMS connector contract; `Enrollment` remains for current audit compatibility.
```

- [ ] **Step 6: Run example smoke tests**

Run:

```bash
COMPLYOS_CSV_DIR=examples/csv-workforce uv run complyos audit
COMPLYOS_CSV_DIR=examples/csv-campus uv run complyos audit
uv run complyos connectors --profile workforce
mkdir -p .generated
uv run complyos init --profile campus --output .generated/complyos-campus.yaml
```

Expected:

- Both audits exit 0 and print `Gaps found:`.
- Connector table prints `cornerstone` for Workforce.
- Init command writes `.generated/complyos-campus.yaml` and prints `Initialized ComplyOS Campus`. Remove `.generated/` after the smoke check if it is still present.

- [ ] **Step 7: Run docs-adjacent tests**

Run:

```bash
uv run pytest tests/unit/test_csv_connector.py tests/unit/test_cli_profiles.py tests/unit/test_cli_connectors.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add CONTEXT.md README.md ARCHITECTURE.md llms.txt examples/csv-campus examples/csv-workforce
git commit -m "docs: document profiles and learning records"
```

---

### Task 8: Final verification and release-readiness audit

**Files:**
- No code files required unless verification exposes a failure.

- [ ] **Step 1: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS with more than the current 171 tests.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Run type check**

Run:

```bash
uv run mypy complyos --ignore-missing-imports
```

Expected: `Success: no issues found`.

- [ ] **Step 4: Run build**

Run:

```bash
rm -rf dist
uv build
rm -rf dist
```

Expected: wheel and source distribution build successfully, then `dist/` is removed.

- [ ] **Step 5: Run public leak audit before any push or public PR**

Run:

```bash
files="CONTEXT.md README.md ARCHITECTURE.md llms.txt pyproject.toml LICENSE docs/superpowers/specs/2026-06-11-complyos-connectivity-tracks-design.md docs/superpowers/plans/2026-06-11-complyos-connectivity-foundation.md complyos tests examples"
python3 - <<'PY_AUDIT'
from pathlib import Path
patterns = ('absolute macOS home path', 'absolute Linux home path', 'machine temp path')
print('Check manually for:', ', '.join(patterns))
PY_AUDIT
grep -RInE '(api[_-]?key|secret|token|password|credential|BEGIN (RSA|OPENSSH|PRIVATE)|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)' $files || true
grep -RInE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' CONTEXT.md README.md ARCHITECTURE.md llms.txt docs/superpowers examples complyos tests || true
git diff --check
```

Expected:

- No absolute local paths.
- No secrets or token markers.
- Only intentional example emails such as `alice@example.com` or `student1@example.edu`.
- No whitespace errors.

- [ ] **Step 6: Confirm intended git state**

Run:

```bash
git status --short --branch
git log --oneline -8
```

Expected:

- Only intentional tracked changes are present.
- `.omx/` remains untracked unless the user explicitly asks to track it.
- Recent commits show each task commit.

- [ ] **Step 7: Commit the implementation plan if it is not already committed**

Run:

```bash
git add docs/superpowers/plans/2026-06-11-complyos-connectivity-foundation.md
git commit -m "docs: add connectivity foundation implementation plan"
```

Expected: plan committed cleanly.

---

## Self-review

### Spec coverage

- One ComplyOS core with Workforce and Campus tracks: Tasks 4, 5, and 7.
- LearningRecord abstraction: Tasks 1, 2, 3, and 6.
- Connector capability matrix: Task 5.
- CSV/import strength for both tracks: Tasks 3 and 7.
- Profile command direction: Task 4.
- Domain glossary: Task 7.
- Major LMS connector priorities without overbuilding all adapters: Task 5.
- Operator-ready release separation from scale-out: Task 7 docs updates.

### Placeholder scan

This plan intentionally avoids unspecified work. Each code-changing task includes concrete test code, implementation code, commands, and expected results.

### Type consistency

- `LearningRecordStatus` is used consistently in domain, repository, CSV connector, and tests.
- `LearningRecord` fields match the approved spec: source system, source record ID, status, due date, completion, score, exemption, expiry, raw evidence hash, and source payload.
- Profile names are consistently `workforce` and `campus`.
- Connector names are lowercase slugs used by profiles and capability matrix.
