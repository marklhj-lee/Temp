import logging
import time
from typing import Optional
import uuid

from open_webui.internal.db import Base
from open_webui.internal.db_async import get_db
from open_webui.env import SRC_LOG_LEVELS

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON, func
from sqlalchemy import select, update, delete

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# UserGroup DB Schema
####################


class Group(Base):
    __tablename__ = "group"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    permissions = Column(JSON, nullable=True)
    user_ids = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class GroupModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    permissions: Optional[dict] = None
    user_ids: list[str] = []

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class GroupResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: str
    permissions: Optional[dict] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    user_ids: list[str] = []
    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


class GroupForm(BaseModel):
    name: str
    description: str
    permissions: Optional[dict] = None


class GroupUpdateForm(GroupForm):
    user_ids: Optional[list[str]] = None


class GroupTable:
    async def insert_new_group(
        self, user_id: str, form_data: GroupForm
    ) -> Optional[GroupModel]:
        async with get_db() as db:
            group = GroupModel(
                **{
                    **form_data.model_dump(exclude_none=True),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = Group(**group.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return GroupModel.model_validate(result) if result else None
            except Exception:
                return None

    async def get_groups(self) -> list[GroupModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(Group).order_by(Group.updated_at.desc())
                )
            ).scalars().all()
            return [GroupModel.model_validate(group) for group in rows]

    async def get_groups_by_member_id(self, user_id: str) -> list[GroupModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(Group)
                    .where(func.json_array_length(Group.user_ids) > 0)
                    .where(Group.user_ids.cast(String).like(f'%"{user_id}"%'))
                    .order_by(Group.updated_at.desc())
                )
            ).scalars().all()
            return [GroupModel.model_validate(group) for group in rows]

    async def get_group_by_id(self, id: str) -> Optional[GroupModel]:
        try:
            async with get_db() as db:
                group = await db.get(Group, id)
                return GroupModel.model_validate(group) if group else None
        except Exception:
            return None

    async def get_group_user_ids_by_id(self, id: str) -> Optional[list[str]]:
        group = await self.get_group_by_id(id)
        if group:
            return group.user_ids
        else:
            return None

    async def update_group_by_id(
        self, id: str, form_data: GroupUpdateForm, overwrite: bool = False
    ) -> Optional[GroupModel]:
        try:
            async with get_db() as db:
                res = await db.execute(
                    update(Group)
                    .where(Group.id == id)
                    .values(
                        **form_data.model_dump(exclude_none=True),
                        updated_at=int(time.time()),
                    )
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                if (res.rowcount or 0) == 0:
                    return None
                return await self.get_group_by_id(id=id)
        except Exception as e:
            log.exception(e)
            return None

    async def delete_group_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                res = await db.execute(delete(Group).where(Group.id == id))
                await db.commit()
                return (res.rowcount or 0) > 0
        except Exception:
            return False

    async def delete_all_groups(self) -> bool:
        async with get_db() as db:
            try:
                await db.execute(delete(Group))
                await db.commit()
                return True
            except Exception:
                return False

    async def remove_user_from_all_groups(self, user_id: str) -> bool:
        async with get_db() as db:
            try:
                groups = await self.get_groups_by_member_id(user_id)

                for group in groups:
                    new_user_ids = [uid for uid in (group.user_ids or []) if uid != user_id]
                    await db.execute(
                        update(Group)
                        .where(Group.id == group.id)
                        .values(user_ids=new_user_ids, updated_at=int(time.time()))
                        .execution_options(synchronize_session=False)
                    )

                await db.commit()
                return True
            except Exception:
                return False


Groups = GroupTable()
