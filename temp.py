import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField
from open_webui.internal.db_async import get_db
from open_webui.models.users import Users, UserResponse
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON, select, delete

from open_webui.utils.access_control import has_access

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Tools DB Schema
####################
class Tool(Base):
    __tablename__ = "tool"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    name = Column(Text)
    content = Column(Text)
    specs = Column(JSONField)
    meta = Column(JSONField)
    valves = Column(JSONField)

    access_control = Column(JSON, nullable=True)  # Controls data access levels.

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ToolMeta(BaseModel):
    description: Optional[str] = None
    manifest: Optional[dict] = {}


class ToolModel(BaseModel):
    id: str
    user_id: str
    name: str
    content: str
    specs: list[dict]
    meta: ToolMeta
    access_control: Optional[dict] = None

    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################
class ToolUserModel(ToolModel):
    user: Optional[UserResponse] = None


class ToolResponse(BaseModel):
    id: str
    user_id: str
    name: str
    meta: ToolMeta
    access_control: Optional[dict] = None
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch


class ToolUserResponse(ToolResponse):
    user: Optional[UserResponse] = None


class ToolForm(BaseModel):
    id: str
    name: str
    content: str
    meta: ToolMeta
    access_control: Optional[dict] = None


class ToolValves(BaseModel):
    valves: Optional[dict] = None


class ToolsTable:
    async def insert_new_tool(
        self, user_id: str, form_data: ToolForm, specs: list[dict]
    ) -> Optional[ToolModel]:
        async with get_db() as db:
            tool = ToolModel(
                **{
                    **form_data.model_dump(),
                    "specs": specs,
                    "user_id": user_id,
                    "updated_at": int(time.time()),
                    "created_at": int(time.time()),
                }
            )
            try:
                row = Tool(**tool.model_dump())
                db.add(row)
                await db.commit()
                await db.refresh(row)
                return ToolModel.model_validate(row) if row else None
            except Exception as e:
                log.exception(f"Error creating a new tool: {e}")
                return None

    async def get_tool_by_id(self, id: str) -> Optional[ToolModel]:
        try:
            async with get_db() as db:
                row = await db.get(Tool, id)
                return ToolModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_tools(self) -> list[ToolUserModel]:
        async with get_db() as db:
            res = await db.execute(select(Tool).order_by(Tool.updated_at.desc()))
            rows = res.scalars().all()

            tools: list[ToolUserModel] = []
            for t in rows:
                user = await Users.get_user_by_id(t.user_id)  # async in this PR
                tools.append(
                    ToolUserModel.model_validate(
                        {
                            **ToolModel.model_validate(t).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return tools

    async def get_tools_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ToolUserModel]:
        tools = await self.get_tools()
        return [
            tool
            for tool in tools
            if tool.user_id == user_id
            or has_access(user_id, permission, tool.access_control)
        ]

    async def get_tool_valves_by_id(self, id: str) -> Optional[dict]:
        try:
            async with get_db() as db:
                row = await db.get(Tool, id)
                return row.valves if row and row.valves else {}
        except Exception as e:
            log.exception(f"Error getting tool valves by id {id}: {e}")
            return None

    async def update_tool_valves_by_id(self, id: str, valves: dict) -> Optional[ToolValves]:
        try:
            async with get_db() as db:
                row = await db.get(Tool, id)
                if not row:
                    return None
                row.valves = valves
                row.updated_at = int(time.time())
                await db.commit()
                # original code returned get_tool_by_id(id); keep behavior minimal:
                return await self.get_tool_by_id(id)
        except Exception:
            return None

    async def get_user_valves_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[dict]:
        try:
            user = await Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if (user and user.settings) else {}

            if "tools" not in user_settings:
                user_settings["tools"] = {}
            if "valves" not in user_settings["tools"]:
                user_settings["tools"]["valves"] = {}

            return user_settings["tools"]["valves"].get(id, {})
        except Exception as e:
            log.exception(
                f"Error getting user values by id {id} and user_id {user_id}: {e}"
            )
            return None

    async def update_user_valves_by_id_and_user_id(
        self, id: str, user_id: str, valves: dict
    ) -> Optional[dict]:
        try:
            user = await Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if (user and user.settings) else {}

            if "tools" not in user_settings:
                user_settings["tools"] = {}
            if "valves" not in user_settings["tools"]:
                user_settings["tools"]["valves"] = {}

            user_settings["tools"]["valves"][id] = valves

            # Persist user settings
            await Users.update_user_by_id(user_id, {"settings": user_settings})

            return user_settings["tools"]["valves"][id]
        except Exception as e:
            log.exception(
                f"Error updating user valves by id {id} and user_id {user_id}: {e}"
            )
            return None

    async def update_tool_by_id(self, id: str, updated: dict) -> Optional[ToolModel]:
        try:
            async with get_db() as db:
                row = await db.get(Tool, id)
                if not row:
                    return None
                for k, v in updated.items():
                    setattr(row, k, v)
                row.updated_at = int(time.time())

                await db.commit()
                await db.refresh(row)
                return ToolModel.model_validate(row)
        except Exception:
            return None

    async def delete_tool_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Tool).where(Tool.id == id))
                await db.commit()
                return True
        except Exception:
            return False


Tools = ToolsTable()