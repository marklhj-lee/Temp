import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base
from open_webui.internal.db_async import get_db

from open_webui.models.chats import Chats  # (unused here, left as-is)
from open_webui.env import SRC_LOG_LEVELS

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, JSON
from sqlalchemy import select, delete

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Feedback DB Schema
####################

class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    version = Column(BigInteger, default=0)
    type = Column(Text)
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    snapshot = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FeedbackModel(BaseModel):
    id: str
    user_id: str
    version: int
    type: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    snapshot: Optional[dict] = None
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################

class FeedbackResponse(BaseModel):
    id: str
    user_id: str
    version: int
    type: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    created_at: int
    updated_at: int


class RatingData(BaseModel):
    rating: Optional[str | int] = None
    model_id: Optional[str] = None
    sibling_model_ids: Optional[list[str]] = None
    reason: Optional[str] = None
    comment: Optional[str] = None
    model_config = ConfigDict(extra="allow", protected_namespaces=())


class MetaData(BaseModel):
    arena: Optional[bool] = None
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    tags: Optional[list[str]] = None
    model_config = ConfigDict(extra="allow")


class SnapshotData(BaseModel):
    chat: Optional[dict] = None
    model_config = ConfigDict(extra="allow")


class FeedbackForm(BaseModel):
    type: str
    data: Optional[RatingData] = None
    meta: Optional[dict] = None
    snapshot: Optional[SnapshotData] = None
    model_config = ConfigDict(extra="allow")


class FeedbackTable:
    async def insert_new_feedback(
        self, user_id: str, form_data: FeedbackForm
    ) -> Optional[FeedbackModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            feedback = FeedbackModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "version": 0,
                    **form_data.model_dump(),
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = Feedback(**feedback.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return FeedbackModel.model_validate(result) if result else None
            except Exception as e:
                await db.rollback()
                log.exception(f"Error creating a new feedback: {e}")
                return None

    async def get_feedback_by_id(self, id: str) -> Optional[FeedbackModel]:
        try:
            async with get_db() as db:
                row = await db.get(Feedback, id)
                if not row:
                    return None
                return FeedbackModel.model_validate(row)
        except Exception:
            return None

    async def get_feedback_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[FeedbackModel]:
        try:
            async with get_db() as db:
                row = (
                    await db.execute(
                        select(Feedback).where(Feedback.id == id, Feedback.user_id == user_id)
                    )
                ).scalar_one_or_none()
                if not row:
                    return None
                return FeedbackModel.model_validate(row)
        except Exception:
            return None

    async def get_all_feedbacks(self) -> list[FeedbackModel]:
        async with get_db() as db:
            rows = (
                await db.execute(select(Feedback).order_by(Feedback.updated_at.desc()))
            ).scalars().all()
            return [FeedbackModel.model_validate(r) for r in rows]

    async def get_feedbacks_by_type(self, type: str) -> list[FeedbackModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(Feedback)
                    .where(Feedback.type == type)
                    .order_by(Feedback.updated_at.desc())
                )
            ).scalars().all()
            return [FeedbackModel.model_validate(r) for r in rows]

    async def get_feedbacks_by_user_id(self, user_id: str) -> list[FeedbackModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(Feedback)
                    .where(Feedback.user_id == user_id)
                    .order_by(Feedback.updated_at.desc())
                )
            ).scalars().all()
            return [FeedbackModel.model_validate(r) for r in rows]

    async def update_feedback_by_id(
        self, id: str, form_data: FeedbackForm
    ) -> Optional[FeedbackModel]:
        async with get_db() as db:
            row = await db.get(Feedback, id)
            if not row:
                return None

            if form_data.data:
                row.data = form_data.data.model_dump()
            if form_data.meta:
                row.meta = form_data.meta
            if form_data.snapshot:
                row.snapshot = form_data.snapshot.model_dump()

            row.updated_at = int(time.time())

            await db.commit()
            await db.refresh(row)
            return FeedbackModel.model_validate(row)

    async def update_feedback_by_id_and_user_id(
        self, id: str, user_id: str, form_data: FeedbackForm
    ) -> Optional[FeedbackModel]:
        async with get_db() as db:
            row = (
                await db.execute(
                    select(Feedback).where(Feedback.id == id, Feedback.user_id == user_id)
                )
            ).scalar_one_or_none()
            if not row:
                return None

            if form_data.data:
                row.data = form_data.data.model_dump()
            if form_data.meta:
                row.meta = form_data.meta
            if form_data.snapshot:
                row.snapshot = form_data.snapshot.model_dump()

            row.updated_at = int(time.time())

            await db.commit()
            await db.refresh(row)
            return FeedbackModel.model_validate(row)

    async def delete_feedback_by_id(self, id: str) -> bool:
        async with get_db() as db:
            row = await db.get(Feedback, id)
            if not row:
                return False
            await db.delete(row)
            await db.commit()
            return True

    async def delete_feedback_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        async with get_db() as db:
            row = (
                await db.execute(
                    select(Feedback).where(Feedback.id == id, Feedback.user_id == user_id)
                )
            ).scalar_one_or_none()
            if not row:
                return False
            await db.delete(row)
            await db.commit()
            return True

    async def delete_feedbacks_by_user_id(self, user_id: str) -> bool:
        async with get_db() as db:
            res = await db.execute(delete(Feedback).where(Feedback.user_id == user_id))
            await db.commit()
            return (res.rowcount or 0) > 0

    async def delete_all_feedbacks(self) -> bool:
        async with get_db() as db:
            res = await db.execute(delete(Feedback))
            await db.commit()
            return (res.rowcount or 0) > 0


Feedbacks = FeedbackTable()
