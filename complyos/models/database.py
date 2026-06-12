"""SQLAlchemy ORM models for local SQLite storage."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class DBUser(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    employment_status: Mapped[str] = mapped_column(String, default="active")
    manager_id: Mapped[str | None] = mapped_column(String, nullable=True)
    job_title: Mapped[str | None] = mapped_column(String, nullable=True)
    custom_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    enrollments: Mapped[list[DBEnrollment]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class DBCourse(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mandatory: Mapped[bool] = mapped_column(default=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)

    enrollments: Mapped[list[DBEnrollment]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class DBEnrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    assigned_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    user: Mapped[DBUser] = relationship(back_populates="enrollments")
    course: Mapped[DBCourse] = relationship(back_populates="enrollments")


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


class DBAuditSnapshot(Base):
    """Point-in-time record of an audit run, used for digest diffing."""

    __tablename__ = "audit_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    gaps_found: Mapped[int] = mapped_column(Integer, nullable=False)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    gaps_by_severity: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String, nullable=False)


class DBEvidenceLedger(Base):
    __tablename__ = "evidence_ledger"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    query_type: Mapped[str] = mapped_column(String, nullable=False)
    query_params: Mapped[str] = mapped_column(String, nullable=False)
    raw_data_hash: Mapped[str] = mapped_column(String, nullable=False)
    transformation_steps: Mapped[str] = mapped_column(String, nullable=False)
    output_hash: Mapped[str] = mapped_column(String, nullable=False)
    output_summary: Mapped[str] = mapped_column(String, nullable=False)


class DBTenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    track_default: Mapped[str] = mapped_column(String, default="workforce")
    status: Mapped[str] = mapped_column(String, default="active")
    data_region: Mapped[str | None] = mapped_column(String, nullable=True)
    processing_purpose: Mapped[str | None] = mapped_column(String, nullable=True)
    data_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    retention_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    subprocessor_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DBActor(Base):
    __tablename__ = "actors"
    __table_args__ = (UniqueConstraint("tenant_id", "auth_subject", name="uq_actor_auth_subject"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="local-default", nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, default="human")
    auth_subject: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DBRoleBinding(Base):
    __tablename__ = "role_bindings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="local-default", nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    permissions_override: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DBAuditActionLog(Base):
    __tablename__ = "audit_action_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="local-default", nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    surface: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str] = mapped_column(String, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    redacted_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DBImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_system",
            "profile",
            "raw_file_hash",
            name="uq_import_batch_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="local-default", nullable=False)
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    profile: Mapped[str] = mapped_column(String, nullable=False)
    raw_file_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    promoted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    batch_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DBImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_import_row_number"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    validation_status: Mapped[str] = mapped_column(String, nullable=False)
    rejection_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class DBImportDecision(Base):
    __tablename__ = "import_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, nullable=False)
    row_id: Mapped[str] = mapped_column(String, nullable=False)
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    decision_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decided_by: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class DBApproval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="local-default", nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[str] = mapped_column(String, nullable=False)
    approval_type: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DBAIProposal(Base):
    __tablename__ = "ai_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, default="local-default", nullable=False)
    proposal_type: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    output_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PROPOSED")
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DBAIProvenance(Base):
    __tablename__ = "ai_provenance"

    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_provider: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String, nullable=False)
    redaction_policy: Mapped[str] = mapped_column(String, nullable=False)
    response_hash: Mapped[str] = mapped_column(String, nullable=False)
    usage_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def resolve_database_url(database: str | None = None) -> str:
    """Resolve a SQLAlchemy database URL from env, URL, or SQLite path."""
    env_url = os.getenv("COMPLYOS_DATABASE_URL")
    if env_url:
        return env_url

    value = database or "complyos.db"
    if "://" in value:
        return value
    return f"sqlite:///{value}"


def init_db(db_path: str = "complyos.db") -> sessionmaker:
    engine = create_engine(resolve_database_url(db_path))
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    with maker() as session:
        if session.get(DBTenant, "local-default") is None:
            session.add(
                DBTenant(
                    id="local-default",
                    name="Local Default Tenant",
                    track_default="workforce",
                    status="active",
                    processing_purpose="local learning-compliance operations",
                    data_categories=["workforce_learning_records"],
                    retention_policy={"mode": "local_default", "review": "required"},
                )
            )
            session.commit()
    return maker
