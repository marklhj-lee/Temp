import json
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base
from open_webui.internal.db_async import get_db

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, String, Text, JSON
from sqlalchemy import select, delete

####################
# Message DB Schema
####################


class MessageReaction(Base):
    __tablename__ = "message_reaction"
    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    message_id = Column(Text)
    name = Column(Text)
    created_at = Column(BigInteger)


class MessageReactionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    message_id: str
    name: str
    created_at: int  # timestamp in epoch


class Message(Base):
    __tablename__ = "message"
    id = Column(Text, primary_key=True)

    user_id = Column(Text)
    channel_id = Column(Text, nullable=True)

    parent_id = Column(Text, nullable=True)

    content = Column(Text)
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    created_at = Column(BigInteger)  # time_ns
    updated_at = Column(BigInteger)  # time_ns


class MessageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    channel_id: Optional[str] = None

    parent_id: Optional[str] = None

    content: str
    data: Optional[dict] = None
    meta: Optional[dict] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class MessageForm(BaseModel):
    content: str
    parent_id: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None


class Reactions(BaseModel):
    name: str
    user_ids: list[str]
    count: int


class MessageResponse(MessageModel):
    latest_reply_at: Optional[int]
    reply_count: int
    reactions: list[Reactions]


class MessageTable:
    async def insert_new_message(
        self, form_data: MessageForm, channel_id: str, user_id: str
    ) -> Optional[MessageModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            ts = int(time.time_ns())

            message = MessageModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "parent_id": form_data.parent_id,
                    "content": form_data.content,
                    "data": form_data.data,
                    "meta": form_data.meta,
                    "created_at": ts,
                    "updated_at": ts,
                }
            )

            result = Message(**message.model_dump())
            db.add(result)
            await db.commit()
            await db.refresh(result)
            return MessageModel.model_validate(result) if result else None

    async def get_message_by_id(self, id: str) -> Optional[MessageResponse]:
        async with get_db() as db:
            message = await db.get(Message, id)
            if not message:
                return None

        reactions = await self.get_reactions_by_message_id(id)
        replies = await self.get_replies_by_message_id(id)

        return MessageResponse(
            **{
                **MessageModel.model_validate(message).model_dump(),
                "latest_reply_at": replies[0].created_at if replies else None,
                "reply_count": len(replies),
                "reactions": reactions,
            }
        )

    async def get_replies_by_message_id(self, id: str) -> list[MessageModel]:
        async with get_db() as db:
            res = await db.execute(
                select(Message)
                .filter_by(parent_id=id)
                .order_by(Message.created_at.desc())
            )
            all_messages = res.scalars().all()
            return [MessageModel.model_validate(m) for m in all_messages]

    async def get_reply_user_ids_by_message_id(self, id: str) -> list[str]:
        async with get_db() as db:
            res = await db.execute(select(Message).filter_by(parent_id=id))
            return [m.user_id for m in res.scalars().all()]

    async def get_messages_by_channel_id(
        self, channel_id: str, skip: int = 0, limit: int = 50
    ) -> list[MessageModel]:
        async with get_db() as db:
            res = await db.execute(
                select(Message)
                .filter_by(channel_id=channel_id, parent_id=None)
                .order_by(Message.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            all_messages = res.scalars().all()
            return [MessageModel.model_validate(m) for m in all_messages]

    async def get_messages_by_parent_id(
        self, channel_id: str, parent_id: str, skip: int = 0, limit: int = 50
    ) -> list[MessageModel]:
        async with get_db() as db:
            parent = await db.get(Message, parent_id)
            if not parent:
                return []

            res = await db.execute(
                select(Message)
                .filter_by(channel_id=channel_id, parent_id=parent_id)
                .order_by(Message.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            all_messages = res.scalars().all()

        # If length of all_messages is less than limit, then add the parent message
        if len(all_messages) < limit:
            all_messages.append(parent)

        return [MessageModel.model_validate(m) for m in all_messages]

    async def update_message_by_id(
        self, id: str, form_data: MessageForm
    ) -> Optional[MessageModel]:
        async with get_db() as db:
            message = await db.get(Message, id)
            if not message:
                return None
            message.content = form_data.content
            message.data = form_data.data
            message.meta = form_data.meta
            message.updated_at = int(time.time_ns())
            await db.commit()
            await db.refresh(message)
            return MessageModel.model_validate(message)

    async def add_reaction_to_message(
        self, id: str, user_id: str, name: str
    ) -> Optional[MessageReactionModel]:
        async with get_db() as db:
            reaction_id = str(uuid.uuid4())
            reaction = MessageReactionModel(
                id=reaction_id,
                user_id=user_id,
                message_id=id,
                name=name,
                created_at=int(time.time_ns()),
            )
            result = MessageReaction(**reaction.model_dump())
            db.add(result)
            await db.commit()
            await db.refresh(result)
            return MessageReactionModel.model_validate(result) if result else None

    async def get_reactions_by_message_id(self, id: str) -> list[Reactions]:
        async with get_db() as db:
            res = await db.execute(select(MessageReaction).filter_by(message_id=id))
            all_reactions = res.scalars().all()

        reactions_map: dict[str, dict] = {}
        for r in all_reactions:
            if r.name not in reactions_map:
                reactions_map[r.name] = {"name": r.name, "user_ids": [], "count": 0}
            reactions_map[r.name]["user_ids"].append(r.user_id)
            reactions_map[r.name]["count"] += 1

        return [Reactions(**r) for r in reactions_map.values()]

    async def remove_reaction_by_id_and_user_id_and_name(
        self, id: str, user_id: str, name: str
    ) -> bool:
        async with get_db() as db:
            await db.execute(
                delete(MessageReaction).where(
                    MessageReaction.message_id == id,
                    MessageReaction.user_id == user_id,
                    MessageReaction.name == name,
                )
            )
            await db.commit()
            return True

    async def delete_reactions_by_id(self, id: str) -> bool:
        async with get_db() as db:
            await db.execute(delete(MessageReaction).where(MessageReaction.message_id == id))
            await db.commit()
            return True

    async def delete_replies_by_id(self, id: str) -> bool:
        async with get_db() as db:
            await db.execute(delete(Message).where(Message.parent_id == id))
            await db.commit()
            return True

    async def delete_message_by_id(self, id: str) -> bool:
        async with get_db() as db:
            # Delete the message
            await db.execute(delete(Message).where(Message.id == id))
            # Delete all reactions to this message
            await db.execute(delete(MessageReaction).where(MessageReaction.message_id == id))
            await db.commit()
            return True


Messages = MessageTable()