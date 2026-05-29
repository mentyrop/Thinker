"""SQLAlchemy 2.x модели (declarative, typed Mapped)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    thoughts: Mapped[list["Thought"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Thought(Base):
    __tablename__ = "thoughts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recommended_route: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), default="journal", server_default="journal", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="new", server_default="new", nullable=False
    )

    actionable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    can_delegate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_candidate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    needs_first_step: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    needs_research: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    suggested_first_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_calendar_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_duration_minutes: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30", nullable=False
    )

    # Мини-проекты: сформулированный результат и шаги (LLM или вручную).
    project_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    success_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    llm_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Soft delete: удалённые мысли скрываются из журнала, но не теряются.
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="thoughts")
    calendar_events: Mapped[list["CalendarEvent"]] = relationship(
        back_populates="thought", cascade="all, delete-orphan"
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    thought_id: Mapped[int] = mapped_column(
        ForeignKey("thoughts.id", ondelete="CASCADE"), index=True, nullable=False
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    end_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    google_calendar_url: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    thought: Mapped["Thought"] = relationship(back_populates="calendar_events")
