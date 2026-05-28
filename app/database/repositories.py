"""Репозитории — вся работа с БД инкапсулирована здесь."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CalendarEvent, Thought, User
from app.services.llm_service import ThoughtAnalysis


class UserRepository:
    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


class ThoughtRepository:
    @staticmethod
    async def create(
        session: AsyncSession, user_id: int, raw_text: str
    ) -> Thought:
        thought = Thought(
            user_id=user_id,
            raw_text=raw_text,
            category="journal",
            status="new",
        )
        session.add(thought)
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def get(session: AsyncSession, thought_id: int) -> Thought | None:
        return await session.get(Thought, thought_id)

    @staticmethod
    async def apply_analysis(
        session: AsyncSession, thought: Thought, analysis: ThoughtAnalysis
    ) -> Thought:
        thought.summary = analysis.summary
        thought.type = analysis.type
        thought.recommended_route = analysis.recommended_route
        thought.confidence = analysis.confidence
        thought.actionable = analysis.actionable
        thought.can_delegate = analysis.can_delegate
        thought.calendar_candidate = analysis.calendar_candidate
        thought.needs_first_step = analysis.needs_first_step
        thought.needs_research = analysis.needs_research
        thought.suggested_first_step = analysis.suggested_first_step
        thought.suggested_calendar_title = analysis.suggested_calendar_title
        thought.suggested_duration_minutes = analysis.suggested_duration_minutes
        thought.llm_json = analysis.model_dump()
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def set_category_status(
        session: AsyncSession,
        thought: Thought,
        category: str | None = None,
        status: str | None = None,
    ) -> Thought:
        if category is not None:
            thought.category = category
        if status is not None:
            thought.status = status
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def set_first_step(
        session: AsyncSession, thought: Thought, first_step: str
    ) -> Thought:
        thought.suggested_first_step = first_step
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def set_summary(
        session: AsyncSession, thought: Thought, summary: str
    ) -> Thought:
        thought.summary = summary
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def set_project_goal(
        session: AsyncSession,
        thought: Thought,
        project_goal: str,
        success_criteria: list[str] | None = None,
        project_title: str | None = None,
    ) -> Thought:
        thought.project_goal = project_goal
        if success_criteria is not None:
            thought.success_criteria = success_criteria
        if project_title is not None:
            thought.project_title = project_title
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def set_project_steps(
        session: AsyncSession,
        thought: Thought,
        steps: list[str],
        first_step: str | None = None,
        project_goal: str | None = None,
    ) -> Thought:
        thought.project_steps = steps
        if first_step is not None:
            thought.suggested_first_step = first_step
        if project_goal is not None:
            thought.project_goal = project_goal
        await session.commit()
        await session.refresh(thought)
        return thought

    @staticmethod
    async def last_for_user(
        session: AsyncSession, user_id: int, limit: int = 10
    ) -> list[Thought]:
        result = await session.execute(
            select(Thought)
            .where(Thought.user_id == user_id)
            .order_by(Thought.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def last_to_finish(
        session: AsyncSession, user_id: int, limit: int = 10
    ) -> list[Thought]:
        result = await session.execute(
            select(Thought)
            .where(
                Thought.user_id == user_id,
                Thought.category == "thoughts_to_finish",
            )
            .order_by(Thought.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class CalendarEventRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        thought_id: int,
        title: str,
        description: str | None,
        start_datetime: datetime,
        end_datetime: datetime,
        google_calendar_url: str,
    ) -> CalendarEvent:
        event = CalendarEvent(
            thought_id=thought_id,
            title=title,
            description=description,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            google_calendar_url=google_calendar_url,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    @staticmethod
    async def upcoming_for_user(
        session: AsyncSession, user_id: int, limit: int = 10
    ) -> list[CalendarEvent]:
        result = await session.execute(
            select(CalendarEvent)
            .join(Thought, CalendarEvent.thought_id == Thought.id)
            .where(Thought.user_id == user_id)
            .order_by(CalendarEvent.start_datetime.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
