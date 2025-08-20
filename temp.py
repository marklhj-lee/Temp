import json
import logging
import time
from typing import Optional
import uuid

from open_webui.internal.db import Base  # keep Base from sync module
from open_webui.internal.async_db import get_db  # async session
from open_webui.env import SRC_LOG_LEVELS

from open_webui.models.files import FileMetadataResponse
from open_webui.models.users import Users, UserResponse

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON
from sqlalchemy import select, update, delete

from open_webui.utils.access_control import has_access

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Knowledge DB Schema
####################

class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

####################
# Forms
####################

class KnowledgeUserModel(KnowledgeModel):
    user: Optional[UserResponse] = None


class KnowledgeResponse(KnowledgeModel):
    files: Optional[list[FileMetadataResponse | dict]] = None


class KnowledgeUserResponse(KnowledgeUserModel):
    files: Optional[list[FileMetadataResponse | dict]] = None


class KnowledgeForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None
    access_control: Optional[dict] = None


class KnowledgeTable:
    async def insert_new_knowledge(
        self, user_id: str, form_data: KnowledgeForm
    ) -> Optional[KnowledgeModel]:
        async with get_db() as db:
            knowledge = KnowledgeModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = Knowledge(**knowledge.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return KnowledgeModel.model_validate(result) if result else None
            except Exception:
                return None

    async def get_knowledge_bases(self) -> list[KnowledgeUserModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(Knowledge).order_by(Knowledge.updated_at.desc())
                )
            ).scalars().all()

            knowledge_bases: list[KnowledgeUserModel] = []
            for knowledge in rows:
                # Users.* is still sync in your codebase; keep as-is for now
                user = Users.get_user_by_id(knowledge.user_id)
                knowledge_bases.append(
                    KnowledgeUserModel.model_validate(
                        {
                            **KnowledgeModel.model_validate(knowledge).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return knowledge_bases

    async def get_knowledge_bases_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[KnowledgeUserModel]:
        bases = await self.get_knowledge_bases()
        return [
            kb
            for kb in bases
            if kb.user_id == user_id or has_access(user_id, permission, kb.access_control)
        ]

    async def get_knowledge_by_id(self, id: str) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                knowledge = await db.get(Knowledge, id)
                return KnowledgeModel.model_validate(knowledge) if knowledge else None
        except Exception:
            return None

    async def update_knowledge_by_id(
        self, id: str, form_data: KnowledgeForm, overwrite: bool = False
    ) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Knowledge)
                    .where(Knowledge.id == id)
                    .values(
                        **form_data.model_dump(),
                        updated_at=int(time.time()),
                    )
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                return await self.get_knowledge_by_id(id=id)
        except Exception as e:
            log.exception(e)
            return None

    async def update_knowledge_data_by_id(
        self, id: str, data: dict
    ) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Knowledge)
                    .where(Knowledge.id == id)
                    .values(
                        data=data,
                        updated_at=int(time.time()),
                    )
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                return await self.get_knowledge_by_id(id=id)
        except Exception as e:
            log.exception(e)
            return None

    async def delete_knowledge_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                res = await db.execute(delete(Knowledge).where(Knowledge.id == id))
                await db.commit()
                return (res.rowcount or 0) > 0
        except Exception:
            return False

    async def delete_all_knowledge(self) -> bool:
        async with get_db() as db:
            try:
                await db.execute(delete(Knowledge))
                await db.commit()
                return True
            except Exception:
                return False


Knowledges = KnowledgeTable()
