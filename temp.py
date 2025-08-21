import time
from typing import Optional

from open_webui.internal.db import Base
from open_webui.internal.db_async import get_db  # ← async session
from open_webui.models.users import Users, UserResponse

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON, select, delete

from open_webui.utils.access_control import has_access


####################
# Prompts DB Schema
####################

class Prompt(Base):
    __tablename__ = "prompt"

    command = Column(String, primary_key=True)
    user_id = Column(String)
    title = Column(Text)
    content = Column(Text)
    timestamp = Column(BigInteger)

    access_control = Column(JSON, nullable=True)  # Controls data access levels.


class PromptModel(BaseModel):
    command: str
    user_id: str
    title: str
    content: str
    timestamp: int  # timestamp in epoch

    access_control: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################

class PromptUserResponse(PromptModel):
    user: Optional[UserResponse] = None


class PromptForm(BaseModel):
    command: str
    title: str
    content: str
    access_control: Optional[dict] = None


class PromptsTable:
    async def insert_new_prompt(
        self, user_id: str, form_data: PromptForm
    ) -> Optional[PromptModel]:
        prompt = PromptModel(
            **{
                "user_id": user_id,
                **form_data.model_dump(),
                "timestamp": int(time.time()),
            }
        )

        try:
            async with get_db() as db:
                row = Prompt(**prompt.model_dump())
                db.add(row)
                await db.commit()
                await db.refresh(row)
                return PromptModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_prompt_by_command(self, command: str) -> Optional[PromptModel]:
        try:
            async with get_db() as db:
                res = await db.execute(select(Prompt).filter_by(command=command))
                row = res.scalars().first()
                return PromptModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_prompts(self) -> list[PromptUserResponse]:
        async with get_db() as db:
            res = await db.execute(select(Prompt).order_by(Prompt.timestamp.desc()))
            rows = res.scalars().all()

            prompts: list[PromptUserResponse] = []
            for p in rows:
                user = await Users.get_user_by_id(p.user_id)  # ← async in this PR
                prompts.append(
                    PromptUserResponse.model_validate(
                        {
                            **PromptModel.model_validate(p).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return prompts

    async def get_prompts_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[PromptUserResponse]:
        prompts = await self.get_prompts()
        return [
            prompt
            for prompt in prompts
            if prompt.user_id == user_id
            or has_access(user_id, permission, prompt.access_control)
        ]

    async def update_prompt_by_command(
        self, command: str, form_data: PromptForm
    ) -> Optional[PromptModel]:
        try:
            async with get_db() as db:
                res = await db.execute(select(Prompt).filter_by(command=command))
                row = res.scalars().first()
                if not row:
                    return None
                row.title = form_data.title
                row.content = form_data.content
                row.access_control = form_data.access_control
                row.timestamp = int(time.time())
                await db.commit()
                await db.refresh(row)
                return PromptModel.model_validate(row)
        except Exception:
            return None

    async def delete_prompt_by_command(self, command: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Prompt).where(Prompt.command == command))
                await db.commit()
                return True
        except Exception:
            return False


Prompts = PromptsTable()
