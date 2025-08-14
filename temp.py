import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField  # keep Base from sync db
from open_webui.internal.db_async import get_db     # async session context
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON
from sqlalchemy import select, delete

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Files DB Schema
####################

class File(Base):
    __tablename__ = "file"
    id = Column(String, primary_key=True)
    user_id = Column(String)
    hash = Column(Text, nullable=True)

    filename = Column(Text)
    path = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    path: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: Optional[int]  # timestamp in epoch
    updated_at: Optional[int]  # timestamp in epoch


####################
# Forms
####################

class FileMeta(BaseModel):
    name: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class FileModelResponse(BaseModel):
    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    data: Optional[dict] = None
    meta: FileMeta

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    model_config = ConfigDict(extra="allow")


class FileMetadataResponse(BaseModel):
    id: str
    meta: dict
    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


class FileForm(BaseModel):
    id: str
    hash: Optional[str] = None
    filename: str
    path: str
    data: dict = {}
    meta: dict = {}
    access_control: Optional[dict] = None


class FilesTable:
    async def insert_new_file(self, user_id: str, form_data: FileForm) -> Optional[FileModel]:
        async with get_db() as db:
            file = FileModel(
                **{
                    **form_data.model_dump(),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = File(**file.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                if result:
                    return FileModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                await db.rollback()
                log.exception(f"Error inserting a new file: {e}")
                return None

    async def get_file_by_id(self, id: str) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                return FileModel.model_validate(file) if file else None
            except Exception:
                return None

    async def get_file_metadata_by_id(self, id: str) -> Optional[FileMetadataResponse]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                return FileMetadataResponse(
                    id=file.id,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                )
            except Exception:
                return None

    async def get_files(self) -> list[FileModel]:
        async with get_db() as db:
            rows = (await db.execute(select(File))).scalars().all()
            return [FileModel.model_validate(file) for file in rows]

    async def get_files_by_ids(self, ids: list[str]) -> list[FileModel]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(File)
                    .where(File.id.in_(ids))
                    .order_by(File.updated_at.desc())
                )
            ).scalars().all()
            return [FileModel.model_validate(file) for file in rows]

    async def get_file_metadatas_by_ids(self, ids: list[str]) -> list[FileMetadataResponse]:
        async with get_db() as db:
            rows = (
                await db.execute(
                    select(File)
                    .where(File.id.in_(ids))
                    .order_by(File.updated_at.desc())
                )
            ).scalars().all()
            return [
                FileMetadataResponse(
                    id=file.id,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                )
                for file in rows
            ]

    async def get_files_by_user_id(self, user_id: str) -> list[FileModel]:
        async with get_db() as db:
            rows = (
                await db.execute(select(File).where(File.user_id == user_id))
            ).scalars().all()
            return [FileModel.model_validate(file) for file in rows]

    async def update_file_hash_by_id(self, id: str, hash: str) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                file.hash = hash
                file.updated_at = int(time.time())
                await db.commit()
                await db.refresh(file)
                return FileModel.model_validate(file)
            except Exception:
                return None

    async def update_file_data_by_id(self, id: str, data: dict) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                file.data = {**(file.data or {}), **data}
                file.updated_at = int(time.time())
                await db.commit()
                await db.refresh(file)
                return FileModel.model_validate(file)
            except Exception:
                return None

    async def update_file_metadata_by_id(self, id: str, meta: dict) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                file.meta = {**(file.meta or {}), **meta}
                file.updated_at = int(time.time())
                await db.commit()
                await db.refresh(file)
                return FileModel.model_validate(file)
            except Exception:
                return None

    async def delete_file_by_id(self, id: str) -> bool:
        async with get_db() as db:
            try:
                # DB-level delete
                res = await db.execute(delete(File).where(File.id == id))
                await db.commit()
                return (res.rowcount or 0) > 0
            except Exception:
                return False

    async def delete_all_files(self) -> bool:
        async with get_db() as db:
            try:
                # Unconditional wipe (schema remains)
                res = await db.execute(delete(File))
                await db.commit()
                return (res.rowcount or 0) > 0
            except Exception:
                return False


Files = FilesTable()
