import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base
from open_webui.internal.async_db import get_db
from open_webui.models.chats import Chats

from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean
from sqlalchemy import select, update, delete
from open_webui.utils.access_control import get_permissions


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Folder DB Schema
####################


class Folder(Base):
    __tablename__ = "folder"
    id = Column(Text, primary_key=True)
    parent_id = Column(Text, nullable=True)
    user_id = Column(Text)
    name = Column(Text)
    items = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    is_expanded = Column(Boolean, default=False)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FolderModel(BaseModel):
    id: str
    parent_id: Optional[str] = None
    user_id: str
    name: str
    items: Optional[dict] = None
    meta: Optional[dict] = None
    is_expanded: bool = False
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class FolderForm(BaseModel):
    name: str
    model_config = ConfigDict(extra="allow")


class FolderTable:
    async def insert_new_folder(
        self, user_id: str, name: str, parent_id: Optional[str] = None
    ) -> Optional[FolderModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            folder = FolderModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "name": name,
                    "parent_id": parent_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = Folder(**folder.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                if result:
                    return FolderModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting a new folder: {e}")
                return None

    async def get_folder_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                row = (
                    await db.execute(
                        select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                    )
                ).scalar_one_or_none()

                if not row:
                    return None

                return FolderModel.model_validate(row)
        except Exception:
            return None

    async def get_children_folders_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                folders = []

                async def get_children(folder):
                    children = await self.get_folders_by_parent_id_and_user_id(
                        folder.id, user_id
                    )
                    for child in children:
                        await get_children(child)
                        folders.append(child)

                root = (
                    await db.execute(
                        select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                    )
                ).scalar_one_or_none()
                if not root:
                    return None

                await get_children(FolderModel.model_validate(root))
                return folders
        except Exception:
            return None

    async def get_folders_by_user_id(self, user_id: str) -> list[FolderModel]:
        async with get_db() as db:
            rows = (
                await db.execute(select(Folder).where(Folder.user_id == user_id))
            ).scalars().all()
            return [FolderModel.model_validate(folder) for folder in rows]

    async def get_folder_by_parent_id_and_user_id_and_name(
        self, parent_id: Optional[str], user_id: str, name: str
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                row = (
                    await db.execute(
                        select(Folder)
                        .where(Folder.parent_id == parent_id, Folder.user_id == user_id)
                        .where(Folder.name.ilike(name))
                    )
                ).scalar_one_or_none()

                if not row:
                    return None

                return FolderModel.model_validate(row)
        except Exception as e:
            log.error(f"get_folder_by_parent_id_and_user_id_and_name: {e}")
            return None

    async def get_folders_by_parent_id_and_user_id(
        self, parent_id: Optional[str], user_id: str
    ) -> list[FolderModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(Folder).where(
                        Folder.parent_id == parent_id, Folder.user_id == user_id
                    )
                )
            ).scalars().all()
            return [FolderModel.model_validate(folder) for folder in rows]

    async def update_folder_parent_id_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        parent_id: str,
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                now = int(time.time())
                res = await db.execute(
                    update(Folder)
                    .where(Folder.id == id, Folder.user_id == user_id)
                    .values(parent_id=parent_id, updated_at=now)
                    .execution_options(synchronize_session=False)
                )
                await db.commit()

                if (res.rowcount or 0) == 0:
                    return None

                row = (
                    await db.execute(
                        select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                    )
                ).scalar_one_or_none()
                return FolderModel.model_validate(row) if row else None
        except Exception as e:
            log.error(f"update_folder: {e}")
            return

    async def update_folder_name_by_id_and_user_id(
        self, id: str, user_id: str, name: str
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                folder = (
                    await db.execute(
                        select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                    )
                ).scalar_one_or_none()

                if not folder:
                    return None

                existing_folder = (
                    await db.execute(
                        select(Folder).where(
                            Folder.name == name,
                            Folder.parent_id == folder.parent_id,
                            Folder.user_id == user_id,
                        )
                    )
                ).scalar_one_or_none()

                if existing_folder:
                    return None

                folder.name = name
                folder.updated_at = int(time.time())

                await db.commit()
                await db.refresh(folder)

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return

    async def update_folder_is_expanded_by_id_and_user_id(
        self, id: str, user_id: str, is_expanded: bool
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                folder = (
                    await db.execute(
                        select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                    )
                ).scalar_one_or_none()

                if not folder:
                    return None

                folder.is_expanded = is_expanded
                folder.updated_at = int(time.time())

                await db.commit()
                await db.refresh(folder)

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return

    async def delete_folder_by_id_and_user_id(
        self, id: str, user_id: str, delete_chats=True
    ) -> bool:
        try:
            async with get_db() as db:
                folder = (
                    await db.execute(
                        select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                    )
                ).scalar_one_or_none()
                if not folder:
                    return False

                if delete_chats:
                    await Chats.delete_chats_by_user_id_and_folder_id(
                        user_id, folder.id
                    )

                async def delete_children(f):
                    children = await self.get_folders_by_parent_id_and_user_id(
                        f.id, user_id
                    )
                    for child in children:
                        if delete_chats:
                            await Chats.delete_chats_by_user_id_and_folder_id(
                                user_id, child.id
                            )

                        await delete_children(child)

                        await db.execute(
                            delete(Folder).where(Folder.id == child.id)
                        )
                        await db.commit()

                await delete_children(FolderModel.model_validate(folder))
                await db.execute(delete(Folder).where(Folder.id == id))
                await db.commit()
                return True
        except Exception as e:
            log.error(f"delete_folder: {e}")
            return False


Folders = FolderTable()
