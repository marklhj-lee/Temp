import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField
from open_webui.internal.async_db import get_db
from open_webui.models.users import Users
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, String, Text
from sqlalchemy import select, update, delete

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Functions DB Schema
####################

class Function(Base):
    __tablename__ = "function"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    name = Column(Text)
    type = Column(Text)
    content = Column(Text)
    meta = Column(JSONField)
    valves = Column(JSONField)
    is_active = Column(Boolean)
    is_global = Column(Boolean)
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class FunctionMeta(BaseModel):
    description: Optional[str] = None
    manifest: Optional[dict] = {}


class FunctionModel(BaseModel):
    id: str
    user_id: str
    name: str
    type: str
    content: str
    meta: FunctionMeta
    is_active: bool = False
    is_global: bool = False
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)

####################
# Forms
####################

class FunctionResponse(BaseModel):
    id: str
    user_id: str
    type: str
    name: str
    meta: FunctionMeta
    is_active: bool
    is_global: bool
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch


class FunctionForm(BaseModel):
    id: str
    name: str
    content: str
    meta: FunctionMeta


class FunctionValves(BaseModel):
    valves: Optional[dict] = None


class FunctionsTable:
    async def insert_new_function(
        self, user_id: str, type: str, form_data: FunctionForm
    ) -> Optional[FunctionModel]:
        function = FunctionModel(
            **{
                **form_data.model_dump(),
                "user_id": user_id,
                "type": type,
                "updated_at": int(time.time()),
                "created_at": int(time.time()),
            }
        )

        try:
            async with get_db() as db:
                result = Function(**function.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return FunctionModel.model_validate(result) if result else None
        except Exception as e:
            log.exception(f"Error creating a new function: {e}")
            return None

    async def get_function_by_id(self, id: str) -> Optional[FunctionModel]:
        try:
            async with get_db() as db:
                function = await db.get(Function, id)
                return FunctionModel.model_validate(function) if function else None
        except Exception:
            return None

    async def get_functions(self, active_only=False) -> list[FunctionModel]:
        async with get_db() as db:
            if active_only:
                stmt = select(Function).where(Function.is_active.is_(True))
            else:
                stmt = select(Function)
            rows = (await db.execute(stmt)).scalars().all()
            return [FunctionModel.model_validate(function) for function in rows]

    async def get_functions_by_type(
        self, type: str, active_only=False
    ) -> list[FunctionModel]:
        async with get_db() as db:
            stmt = select(Function).where(Function.type == type)
            if active_only:
                stmt = stmt.where(Function.is_active.is_(True))
            rows = (await db.execute(stmt)).scalars().all()
            return [FunctionModel.model_validate(function) for function in rows]

    async def get_global_filter_functions(self) -> list[FunctionModel]:
        async with get_db() as db:
            stmt = (
                select(Function)
                .where(
                    Function.type == "filter",
                    Function.is_active.is_(True),
                    Function.is_global.is_(True),
                )
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [FunctionModel.model_validate(function) for function in rows]

    async def get_global_action_functions(self) -> list[FunctionModel]:
        async with get_db() as db:
            stmt = (
                select(Function)
                .where(
                    Function.type == "action",
                    Function.is_active.is_(True),
                    Function.is_global.is_(True),
                )
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [FunctionModel.model_validate(function) for function in rows]

    async def get_function_valves_by_id(self, id: str) -> Optional[dict]:
        async with get_db() as db:
            try:
                function = await db.get(Function, id)
                return function.valves if (function and function.valves) else {}
            except Exception as e:
                log.exception(f"Error getting function valves by id {id}: {e}")
                return None

    async def update_function_valves_by_id(
        self, id: str, valves: dict
    ) -> Optional[FunctionValves]:
        async with get_db() as db:
            try:
                func = await db.get(Function, id)
                if not func:
                    return None
                func.valves = valves
                func.updated_at = int(time.time())
                await db.commit()
                await db.refresh(func)
                return await self.get_function_by_id(id)
            except Exception:
                return None

    # Keeping these two as sync for now since Users.* is still sync in your codebase
    def get_user_valves_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[dict]:
        try:
            user = Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if user.settings else {}

            if "functions" not in user_settings:
                user_settings["functions"] = {}
            if "valves" not in user_settings["functions"]:
                user_settings["functions"]["valves"] = {}

            return user_settings["functions"]["valves"].get(id, {})
        except Exception as e:
            log.exception(
                f"Error getting user values by id {id} and user id {user_id}: {e}"
            )
            return None

    def update_user_valves_by_id_and_user_id(
        self, id: str, user_id: str, valves: dict
    ) -> Optional[dict]:
        try:
            user = Users.get_user_by_id(user_id)
            user_settings = user.settings.model_dump() if user.settings else {}

            if "functions" not in user_settings:
                user_settings["functions"] = {}
            if "valves" not in user_settings["functions"]:
                user_settings["functions"]["valves"] = {}

            user_settings["functions"]["valves"][id] = valves
            Users.update_user_by_id(user_id, {"settings": user_settings})
            return user_settings["functions"]["valves"][id]
        except Exception as e:
            log.exception(
                f"Error updating user valves by id {id} and user_id {user_id}: {e}"
            )
            return None

    async def update_function_by_id(self, id: str, updated: dict) -> Optional[FunctionModel]:
        async with get_db() as db:
            try:
                res = await db.execute(
                    update(Function)
                    .where(Function.id == id)
                    .values(**updated, updated_at=int(time.time()))
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                if (res.rowcount or 0) == 0:
                    return None
                return await self.get_function_by_id(id)
            except Exception:
                return None

    async def deactivate_all_functions(self) -> Optional[bool]:
        async with get_db() as db:
            try:
                await db.execute(
                    update(Function)
                    .values(is_active=False, updated_at=int(time.time()))
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                return True
            except Exception:
                return None

    async def delete_function_by_id(self, id: str) -> bool:
        async with get_db() as db:
            try:
                res = await db.execute(delete(Function).where(Function.id == id))
                await db.commit()
                return (res.rowcount or 0) > 0
            except Exception:
                return False


Functions = FunctionsTable()
