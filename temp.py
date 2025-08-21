import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base  # keep Base as-is
from open_webui.internal.db_async import get_db  # ← async session

from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, JSON, PrimaryKeyConstraint, select, delete

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Tag DB Schema (unchanged)
####################
class Tag(Base):
    __tablename__ = "tag"
    id = Column(String)
    name = Column(String)
    user_id = Column(String)
    meta = Column(JSON, nullable=True)

    # Unique constraint ensuring (id, user_id) is unique, not just the `id` column
    __table_args__ = (PrimaryKeyConstraint("id", "user_id", name="pk_id_user_id"),)


class TagModel(BaseModel):
    id: str
    name: str
    user_id: str
    meta: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)


####################
# Forms (unchanged)
####################

class TagChatIdForm(BaseModel):
    name: str
    chat_id: str


class TagTable:
    async def insert_new_tag(self, name: str, user_id: str) -> Optional[TagModel]:
        async with get_db() as db:
            id = name.replace(" ", "_").lower()
            tag = TagModel(**{"id": id, "user_id": user_id, "name": name})
            try:
                row = Tag(**tag.model_dump())
                db.add(row)
                await db.commit()
                await db.refresh(row)
                return TagModel.model_validate(row) if row else None
            except Exception as e:
                log.exception(f"Error inserting a new tag: {e}")
                return None

    async def get_tag_by_name_and_user_id(
        self, name: str, user_id: str
    ) -> Optional[TagModel]:
        try:
            id = name.replace(" ", "_").lower()
            async with get_db() as db:
                res = await db.execute(select(Tag).filter_by(id=id, user_id=user_id))
                row = res.scalars().first()
                return TagModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_tags_by_user_id(self, user_id: str) -> list[TagModel]:
        async with get_db() as db:
            res = await db.execute(select(Tag).filter_by(user_id=user_id))
            rows = res.scalars().all()
            return [TagModel.model_validate(t) for t in rows]

    async def get_tags_by_ids_and_user_id(
        self, ids: list[str], user_id: str
    ) -> list[TagModel]:
        async with get_db() as db:
            res = await db.execute(
                select(Tag).where(Tag.id.in_(ids), Tag.user_id == user_id)
            )
            rows = res.scalars().all()
            return [TagModel.model_validate(t) for t in rows]

    async def delete_tag_by_name_and_user_id(self, name: str, user_id: str) -> bool:
        try:
            async with get_db() as db:
                id = name.replace(" ", "_").lower()
                await db.execute(delete(Tag).where(Tag.id == id, Tag.user_id == user_id))
                await db.commit()
                return True
        except Exception as e:
            log.error(f"delete_tag: {e}")
            return False


Tags = TagTable()