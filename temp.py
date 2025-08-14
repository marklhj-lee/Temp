import logging
import json
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base
from open_webui.internal.async_db import get_db
from open_webui.models.tags import TagModel, Tag, Tags
from open_webui.env import SRC_LOG_LEVELS

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, String, Text, JSON
from sqlalchemy import or_, func, select, and_, text, update, delete

####################
# Chat DB Schema
####################

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class Chat(Base):
    __tablename__ = "chat"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    title = Column(Text)
    chat = Column(JSON)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)

    share_id = Column(Text, unique=True, nullable=True)
    archived = Column(Boolean, default=False)
    pinned = Column(Boolean, default=False, nullable=True)

    meta = Column(JSON, server_default="{}")
    folder_id = Column(Text, nullable=True)


class ChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    chat: dict

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    share_id: Optional[str] = None
    archived: bool = False
    pinned: Optional[bool] = False

    meta: dict = {}
    folder_id: Optional[str] = None


####################
# Forms
####################


class ChatForm(BaseModel):
    chat: dict


class ChatImportForm(ChatForm):
    meta: Optional[dict] = {}
    pinned: Optional[bool] = False
    folder_id: Optional[str] = None


class ChatTitleMessagesForm(BaseModel):
    title: str
    messages: list[dict]


class ChatTitleForm(BaseModel):
    title: str


class ChatResponse(BaseModel):
    id: str
    user_id: str
    title: str
    chat: dict
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch
    share_id: Optional[str] = None  # id of the chat to be shared
    archived: bool
    pinned: Optional[bool] = False
    meta: dict = {}
    folder_id: Optional[str] = None


class ChatTitleIdResponse(BaseModel):
    id: str
    title: str
    updated_at: int
    created_at: int


class ChatTable:
    async def insert_new_chat(self, user_id: str, form_data: ChatForm) -> Optional[ChatModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            chat = ChatModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "title": (
                        form_data.chat["title"]
                        if "title" in form_data.chat
                        else "New Chat"
                    ),
                    "chat": form_data.chat,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            result = Chat(**chat.model_dump())
            db.add(result)
            await db.commit()
            await db.refresh(result)
            return ChatModel.model_validate(result) if result else None

    async def import_chat(
        self, user_id: str, form_data: ChatImportForm
    ) -> Optional[ChatModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            chat = ChatModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "title": (
                        form_data.chat["title"]
                        if "title" in form_data.chat
                        else "New Chat"
                    ),
                    "chat": form_data.chat,
                    "meta": form_data.meta,
                    "pinned": form_data.pinned,
                    "folder_id": form_data.folder_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            result = Chat(**chat.model_dump())
            db.add(result)
            await db.commit()
            await db.refresh(result)
            return ChatModel.model_validate(result) if result else None

    async def update_chat_by_id(self, id: str, chat: dict) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat_item = await db.get(Chat, id)
                if not chat_item:
                    return None
                chat_item.chat = chat
                chat_item.title = chat["title"] if "title" in chat else "New Chat"
                chat_item.updated_at = int(time.time())
                await db.commit()
                await db.refresh(chat_item)
                return ChatModel.model_validate(chat_item)
        except Exception:
            return None

    async def update_chat_title_by_id(self, id: str, title: str) -> Optional[ChatModel]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        chat = chat.chat
        chat["title"] = title

        return await self.update_chat_by_id(id, chat)

    async def update_chat_tags_by_id(
        self, id: str, tags: list[str], user
    ) -> Optional[ChatModel]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        await self.delete_all_tags_by_id_and_user_id(id, user.id)

        for tag in chat.meta.get("tags", []):
            if await self.count_chats_by_tag_name_and_user_id(tag, user.id) == 0:
                Tags.delete_tag_by_name_and_user_id(tag, user.id)

        for tag_name in tags:
            if tag_name.lower() == "none":
                continue

            await self.add_chat_tag_by_id_and_user_id_and_tag_name(id, user.id, tag_name)
        return await self.get_chat_by_id(id)

    async def get_chat_title_by_id(self, id: str) -> Optional[str]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        return chat.chat.get("title", "New Chat")

    async def get_messages_by_chat_id(self, id: str) -> Optional[dict]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        return chat.chat.get("history", {}).get("messages", {}) or {}

    async def get_message_by_id_and_message_id(
        self, id: str, message_id: str
    ) -> Optional[dict]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        return chat.chat.get("history", {}).get("messages", {}).get(message_id, {})

    async def upsert_message_to_chat_by_id_and_message_id(
        self, id: str, message_id: str, message: dict
    ) -> Optional[ChatModel]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        chat = chat.chat
        history = chat.get("history", {})

        if message_id in history.get("messages", {}):
            history["messages"][message_id] = {
                **history["messages"][message_id],
                **message,
            }
        else:
            history["messages"][message_id] = message

        history["currentId"] = message_id

        chat["history"] = history
        return await self.update_chat_by_id(id, chat)

    async def add_message_status_to_chat_by_id_and_message_id(
        self, id: str, message_id: str, status: dict
    ) -> Optional[ChatModel]:
        chat = await self.get_chat_by_id(id)
        if chat is None:
            return None

        chat = chat.chat
        history = chat.get("history", {})

        if message_id in history.get("messages", {}):
            status_history = history["messages"][message_id].get("statusHistory", [])
            status_history.append(status)
            history["messages"][message_id]["statusHistory"] = status_history

        chat["history"] = history
        return await self.update_chat_by_id(id, chat)

    async def insert_shared_chat_by_chat_id(self, chat_id: str) -> Optional[ChatModel]:
        async with get_db() as db:
            chat = await db.get(Chat, chat_id)
            if not chat:
                return None
            if chat.share_id:
                return await self.get_chat_by_id_and_user_id(chat.share_id, "shared")

            shared_chat = ChatModel(
                **{
                    "id": str(uuid.uuid4()),
                    "user_id": f"shared-{chat_id}",
                    "title": chat.title,
                    "chat": chat.chat,
                    "created_at": chat.created_at,
                    "updated_at": int(time.time()),
                }
            )
            shared_result = Chat(**shared_chat.model_dump())
            db.add(shared_result)
            await db.commit()
            await db.refresh(shared_result)

            # minimal-change style: mutate loaded base row and refresh
            chat.share_id = shared_chat.id
            await db.commit()
            await db.refresh(chat)

            return shared_chat

    async def update_shared_chat_by_chat_id(self, chat_id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, chat_id)
                if not chat:
                    return None

                shared_chat = (
                    await db.execute(select(Chat).where(Chat.user_id == f"shared-{chat_id}"))
                ).scalar_one_or_none()

                if shared_chat is None:
                    return await self.insert_shared_chat_by_chat_id(chat_id)

                shared_chat.title = chat.title
                shared_chat.chat = chat.chat

                shared_chat.updated_at = int(time.time())
                await db.commit()
                await db.refresh(shared_chat)

                return ChatModel.model_validate(shared_chat)
        except Exception:
            return None

    async def delete_shared_chat_by_chat_id(self, chat_id: str) -> bool:
        try:
            async with get_db() as db:
                res = await db.execute(delete(Chat).where(Chat.user_id == f"shared-{chat_id}"))
                await db.commit()
                return (res.rowcount or 0) > 0
        except Exception:
            return False

    async def update_chat_share_id_by_id(
        self, id: str, share_id: Optional[str]
    ) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat:
                    return None
                chat.share_id = share_id
                await db.commit()
                await db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def toggle_chat_pinned_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat:
                    return None
                chat.pinned = not chat.pinned
                chat.updated_at = int(time.time())
                await db.commit()
                await db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def toggle_chat_archive_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat:
                    return None
                chat.archived = not chat.archived
                chat.updated_at = int(time.time())
                await db.commit()
                await db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def archive_all_chats_by_user_id(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Chat)
                    .where(Chat.user_id == user_id)
                    .values(archived=True)
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                return True
        except Exception:
            return False

    async def get_archived_chat_list_by_user_id(
        self, user_id: str, skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        async with get_db() as db:
            all_chats = (
                await db.execute(
                    select(Chat)
                    .where(Chat.user_id == user_id, Chat.archived.is_(True))
                    .order_by(Chat.updated_at.desc())
                )
            ).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chat_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ChatModel]:
        async with get_db() as db:
            stmt = select(Chat).where(Chat.user_id == user_id)
            if not include_archived:
                stmt = stmt.where(Chat.archived.is_(False))

            stmt = stmt.order_by(Chat.updated_at.desc())

            if skip:
                stmt = stmt.offset(skip)
            if limit:
                stmt = stmt.limit(limit)

            all_chats = (await db.execute(stmt)).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chat_title_id_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[ChatTitleIdResponse]:
        async with get_db() as db:
            stmt = (
                select(Chat.id, Chat.title, Chat.updated_at, Chat.created_at)
                .where(Chat.user_id == user_id)
                .where(Chat.folder_id.is_(None))
                .where(or_(Chat.pinned == False, Chat.pinned.is_(None)))
            )

            if not include_archived:
                stmt = stmt.where(Chat.archived.is_(False))

            stmt = stmt.order_by(Chat.updated_at.desc())

            if skip:
                stmt = stmt.offset(skip)
            if limit:
                stmt = stmt.limit(limit)

            rows = (await db.execute(stmt)).all()

            return [
                ChatTitleIdResponse.model_validate(
                    {
                        "id": row[0],
                        "title": row[1],
                        "updated_at": row[2],
                        "created_at": row[3],
                    }
                )
                for row in rows
            ]

    async def get_chat_list_by_chat_ids(
        self, chat_ids: list[str], skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        async with get_db() as db:
            all_chats = (
                await db.execute(
                    select(Chat)
                    .where(Chat.id.in_(chat_ids), Chat.archived.is_(False))
                    .order_by(Chat.updated_at.desc())
                )
            ).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chat_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                return ChatModel.model_validate(chat) if chat else None
        except Exception:
            return None

    async def get_chat_by_share_id(self, id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = (
                    await db.execute(select(Chat).where(Chat.share_id == id))
                ).scalar_one_or_none()

                if chat:
                    return await self.get_chat_by_id(id)
                else:
                    return None
        except Exception:
            return None

    async def get_chat_by_id_and_user_id(self, id: str, user_id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = (
                    await db.execute(select(Chat).where(Chat.id == id, Chat.user_id == user_id))
                ).scalar_one_or_none()
                return ChatModel.model_validate(chat) if chat else None
        except Exception:
            return None

    async def get_chats(self, skip: int = 0, limit: int = 50) -> list[ChatModel]:
        async with get_db() as db:
            all_chats = (
                await db.execute(select(Chat).order_by(Chat.updated_at.desc()))
            ).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        async with get_db() as db:
            all_chats = (
                await db.execute(
                    select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
                )
            ).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_pinned_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        async with get_db() as db:
            all_chats = (
                await db.execute(
                    select(Chat)
                    .where(Chat.user_id == user_id, Chat.pinned.is_(True), Chat.archived.is_(False))
                    .order_by(Chat.updated_at.desc())
                )
            ).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_archived_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        async with get_db() as db:
            all_chats = (
                await db.execute(
                    select(Chat)
                    .where(Chat.user_id == user_id, Chat.archived.is_(True))
                    .order_by(Chat.updated_at.desc())
                )
            ).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chats_by_user_id_and_search_text(
        self,
        user_id: str,
        search_text: str,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 60,
    ) -> list[ChatModel]:
        """
        Filters chats based on a search query using Python, allowing pagination using skip and limit.
        """
        search_text = search_text.lower().strip()

        if not search_text:
            return await self.get_chat_list_by_user_id(user_id, include_archived, skip, limit)

        search_text_words = search_text.split(" ")

        tag_ids = [
            word.replace("tag:", "").replace(" ", "_").lower()
            for word in search_text_words
            if word.startswith("tag:")
        ]

        search_text_words = [
            word for word in search_text_words if not word.startswith("tag:")
        ]

        search_text = " ".join(search_text_words)

        async with get_db() as db:
            stmt = select(Chat).where(Chat.user_id == user_id)

            if not include_archived:
                stmt = stmt.where(Chat.archived == False)

            stmt = stmt.order_by(Chat.updated_at.desc())

            dialect_name = db.bind.dialect.name
            if dialect_name == "sqlite":
                stmt = stmt.where(
                    (
                        Chat.title.ilike(f"%{search_text}%")
                        | text(
                            """
                            EXISTS (
                                SELECT 1 
                                FROM json_each(Chat.chat, '$.messages') AS message 
                                WHERE LOWER(message.value->>'content') LIKE '%' || :search_text || '%'
                            )
                            """
                        )
                    ).params(search_text=search_text)
                )

                if "none" in tag_ids:
                    stmt = stmt.where(
                        text(
                            """
                            NOT EXISTS (
                                SELECT 1
                                FROM json_each(Chat.meta, '$.tags') AS tag
                            )
                            """
                        )
                    )
                elif tag_ids:
                    stmt = stmt.where(
                        and_(
                            *[
                                text(
                                    f"""
                                    EXISTS (
                                        SELECT 1
                                        FROM json_each(Chat.meta, '$.tags') AS tag
                                        WHERE tag.value = :tag_id_{tag_idx}
                                    )
                                    """
                                ).params(**{f"tag_id_{tag_idx}": tag_id})
                                for tag_idx, tag_id in enumerate(tag_ids)
                            ]
                        )
                    )

            elif dialect_name == "postgresql":
                stmt = stmt.where(
                    (
                        Chat.title.ilike(f"%{search_text}%")
                        | text(
                            """
                            EXISTS (
                                SELECT 1
                                FROM json_array_elements(Chat.chat->'messages') AS message
                                WHERE LOWER(message->>'content') LIKE '%' || :search_text || '%'
                            )
                            """
                        )
                    ).params(search_text=search_text)
                )

                if "none" in tag_ids:
                    stmt = stmt.where(
                        text(
                            """
                            NOT EXISTS (
                                SELECT 1
                                FROM json_array_elements_text(Chat.meta->'tags') AS tag
                            )
                            """
                        )
                    )
                elif tag_ids:
                    stmt = stmt.where(
                        and_(
                            *[
                                text(
                                    f"""
                                    EXISTS (
                                        SELECT 1
                                        FROM json_array_elements_text(Chat.meta->'tags') AS tag
                                        WHERE tag = :tag_id_{tag_idx}
                                    )
                                    """
                                ).params(**{f"tag_id_{tag_idx}": tag_id})
                                for tag_idx, tag_id in enumerate(tag_ids)
                            ]
                        )
                    )
            else:
                raise NotImplementedError(
                    f"Unsupported dialect: {db.bind.dialect.name}"
                )

            stmt = stmt.offset(skip).limit(limit)
            all_chats = (await db.execute(stmt)).scalars().all()

            log.info(f"The number of chats: {len(all_chats)}")

            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chats_by_folder_id_and_user_id(
        self, folder_id: str, user_id: str
    ) -> list[ChatModel]:
        async with get_db() as db:
            stmt = (
                select(Chat)
                .where(Chat.folder_id == folder_id, Chat.user_id == user_id)
                .where(or_(Chat.pinned == False, Chat.pinned == None))
                .where(Chat.archived == False)
                .order_by(Chat.updated_at.desc())
            )
            all_chats = (await db.execute(stmt)).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def get_chats_by_folder_ids_and_user_id(
        self, folder_ids: list[str], user_id: str
    ) -> list[ChatModel]:
        async with get_db() as db:
            stmt = (
                select(Chat)
                .where(Chat.folder_id.in_(folder_ids), Chat.user_id == user_id)
                .where(or_(Chat.pinned == False, Chat.pinned == None))
                .where(Chat.archived == False)
                .order_by(Chat.updated_at.desc())
            )
            all_chats = (await db.execute(stmt)).scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def update_chat_folder_id_by_id_and_user_id(
        self, id: str, user_id: str, folder_id: str
    ) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat:
                    return None
                chat.folder_id = folder_id
                chat.updated_at = int(time.time())
                chat.pinned = False
                await db.commit()
                await db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def get_chat_tags_by_id_and_user_id(self, id: str, user_id: str) -> list[TagModel]:
        async with get_db() as db:
            chat = await db.get(Chat, id)
            tags = chat.meta.get("tags", []) if chat and chat.meta else []
            return [Tags.get_tag_by_name_and_user_id(tag, user_id) for tag in tags]

    async def get_chat_list_by_user_id_and_tag_name(
        self, user_id: str, tag_name: str, skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        async with get_db() as db:
            stmt = select(Chat).where(Chat.user_id == user_id)
            tag_id = tag_name.replace(" ", "_").lower()

            log.info(f"DB dialect name: {db.bind.dialect.name}")
            if db.bind.dialect.name == "sqlite":
                stmt = stmt.where(
                    text(
                        "EXISTS (SELECT 1 FROM json_each(Chat.meta, '$.tags') WHERE json_each.value = :tag_id)"
                    ).params(tag_id=tag_id)
                )
            elif db.bind.dialect.name == "postgresql":
                stmt = stmt.where(
                    text(
                        "EXISTS (SELECT 1 FROM json_array_elements_text(Chat.meta->'tags') elem WHERE elem = :tag_id)"
                    ).params(tag_id=tag_id)
                )
            else:
                raise NotImplementedError(
                    f"Unsupported dialect: {db.bind.dialect.name}"
                )

            all_chats = (await db.execute(stmt)).scalars().all()
            log.debug(f"all_chats: {all_chats}")
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def add_chat_tag_by_id_and_user_id_and_tag_name(
        self, id: str, user_id: str, tag_name: str
    ) -> Optional[ChatModel]:
        tag = Tags.get_tag_by_name_and_user_id(tag_name, user_id)
        if tag is None:
            tag = Tags.insert_new_tag(tag_name, user_id)
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)

                tag_id = tag.id
                if tag_id not in (chat.meta or {}).get("tags", []):
                    chat.meta = {
                        **(chat.meta or {}),
                        "tags": list(set((chat.meta or {}).get("tags", []) + [tag_id])),
                    }

                await db.commit()
                await db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def count_chats_by_tag_name_and_user_id(self, tag_name: str, user_id: str) -> int:
        async with get_db() as db:
            stmt = select(func.count()).select_from(Chat).where(Chat.user_id == user_id, Chat.archived == False)

            tag_id = tag_name.replace(" ", "_").lower()

            if db.bind.dialect.name == "sqlite":
                stmt = stmt.where(
                    text(
                        "EXISTS (SELECT 1 FROM json_each(Chat.meta, '$.tags') WHERE json_each.value = :tag_id)"
                    ).params(tag_id=tag_id)
                )

            elif db.bind.dialect.name == "postgresql":
                stmt = stmt.where(
                    text(
                        "EXISTS (SELECT 1 FROM json_array_elements_text(Chat.meta->'tags') elem WHERE elem = :tag_id)"
                    ).params(tag_id=tag_id)
                )

            else:
                raise NotImplementedError(
                    f"Unsupported dialect: {db.bind.dialect.name}"
                )

            count = (await db.execute(stmt)).scalar_one()
            log.info(f"Count of chats for tag '{tag_name}': {count}")

            return int(count)

    async def delete_tag_by_id_and_user_id_and_tag_name(
        self, id: str, user_id: str, tag_name: str
    ) -> bool:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                tags = (chat.meta or {}).get("tags", []) if chat else []
                tag_id = tag_name.replace(" ", "_").lower()

                tags = [tag for tag in tags if tag != tag_id]
                chat.meta = {
                    **(chat.meta or {}),
                    "tags": list(set(tags)),
                }
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_all_tags_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                chat.meta = {
                    **(chat.meta or {}),
                    "tags": [],
                }
                await db.commit()

                return True
        except Exception:
            return False

    async def delete_chat_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Chat).where(Chat.id == id))
                await db.commit()

            return True and await self.delete_shared_chat_by_chat_id(id)
        except Exception:
            return False

    async def delete_chat_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Chat).where(Chat.id == id, Chat.user_id == user_id))
                await db.commit()

            return True and await self.delete_shared_chat_by_chat_id(id)
        except Exception:
            return False

    async def delete_chats_by_user_id(self, user_id: str) -> bool:
        try:
            await self.delete_shared_chats_by_user_id(user_id)
            async with get_db() as db:
                await db.execute(delete(Chat).where(Chat.user_id == user_id))
                await db.commit()

                return True
        except Exception:
            return False

    async def delete_chats_by_user_id_and_folder_id(
        self, user_id: str, folder_id: str
    ) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Chat).where(Chat.user_id == user_id, Chat.folder_id == folder_id))
                await db.commit()

                return True
        except Exception:
            return False

    async def delete_shared_chats_by_user_id(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                chats_by_user = (
                    await db.execute(select(Chat).where(Chat.user_id == user_id))
                ).scalars().all()
                shared_chat_ids = [f"shared-{chat.id}" for chat in chats_by_user]

                if shared_chat_ids:
                    await db.execute(delete(Chat).where(Chat.user_id.in_(shared_chat_ids)))
                    await db.commit()

                return True
        except Exception:
            return False


Chats = ChatTable()
