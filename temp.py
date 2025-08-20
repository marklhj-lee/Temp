import time
import uuid
from typing import Optional

from open_webui.internal.db import Base  # unchanged
from open_webui.internal.async_db import get_db  # ⬅️ async session
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text
from sqlalchemy import select, update, delete  # ⬅️ for async queries

####################
# Memory DB Schema
####################

class Memory(Base):
    __tablename__ = "memory"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    content = Column(Text)
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)

class MemoryModel(BaseModel):
    id: str
    user_id: str
    content: str
    updated_at: int
    created_at: int
    model_config = ConfigDict(from_attributes=True)

####################
# Table
####################

class MemoriesTable:
    async def insert_new_memory(
        self,
        user_id: str,
        content: str,
    ) -> Optional[MemoryModel]:
        async with get_db() as db:
            id_ = str(uuid.uuid4())
            now = int(time.time())

            row = Memory(
                id=id_,
                user_id=user_id,
                content=content,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return MemoryModel.model_validate(row) if row else None

    async def update_memory_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        content: str,
    ) -> Optional[MemoryModel]:
        async with get_db() as db:
            now = int(time.time())
            res = await db.execute(
                update(Memory)
                .where(Memory.id == id, Memory.user_id == user_id)
                .values(content=content, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            if (res.rowcount or 0) == 0:
                return None
            # fetch updated row
            row = await db.get(Memory, id)
            return MemoryModel.model_validate(row) if row else None

    async def get_memories(self) -> Optional[list[MemoryModel]]:
        async with get_db() as db:
            try:
                rows = (await db.execute(select(Memory))).scalars().all()
                return [MemoryModel.model_validate(r) for r in rows]
            except Exception:
                return None

    async def get_memories_by_user_id(self, user_id: str) -> Optional[list[MemoryModel]]:
        async with get_db() as db:
            try:
                rows = (
                    await db.execute(select(Memory).where(Memory.user_id == user_id))
                ).scalars().all()
                return [MemoryModel.model_validate(r) for r in rows]
            except Exception:
                return None

    async def get_memory_by_id(self, id: str) -> Optional[MemoryModel]:
        async with get_db() as db:
            try:
                row = await db.get(Memory, id)
                return MemoryModel.model_validate(row) if row else None
            except Exception:
                return None

    async def delete_memory_by_id(self, id: str) -> bool:
        async with get_db() as db:
            try:
                res = await db.execute(delete(Memory).where(Memory.id == id))
                await db.commit()
                return (res.rowcount or 0) > 0
            except Exception:
                return False

    async def delete_memories_by_user_id(self, user_id: str) -> bool:
        async with get_db() as db:
            try:
                res = await db.execute(delete(Memory).where(Memory.user_id == user_id))
                await db.commit()
                return (res.rowcount or 0) > 0
            except Exception:
                return False

    async def delete_memory_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        async with get_db() as db:
            try:
                res = await db.execute(
                    delete(Memory).where(Memory.id == id, Memory.user_id == user_id)
                )
                await db.commit()
                return (res.rowcount or 0) > 0
            except Exception:
                return False

Memories = MemoriesTable()
