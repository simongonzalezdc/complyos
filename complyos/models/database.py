"""SQLAlchemy ORM models for local SQLite storage."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, create_engine
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


def init_db(db_path: str = "complyos.db") -> sessionmaker:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
