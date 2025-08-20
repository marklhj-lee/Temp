import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField  # keep Base/JSONField
from open_webui.internal.db_async import get_db     # <-- use your async session getter
from open_webui.env import SRC_LOG_LEVELS

from open_webui.models.users import Users, UserResponse

from pydantic import BaseModel, ConfigDict

from sqlalchemy import BigInteger, Column, Text, JSON, Boolean, select, delete
from sqlalchemy import and_

from open_webui.utils.access_control import has_access

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Models DB Schema (unchanged)
####################

class ModelParams(BaseModel):
    model_config = ConfigDict(extra="allow")
    pass


class ModelMeta(BaseModel):
    profile_image_url: Optional[str] = "/static/favicon.png"
    description: Optional[str] = None
    """
        User-facing description of the model.
    """
    capabilities: Optional[dict] = None
    model_config = ConfigDict(extra="allow")
    pass


class Model(Base):
    __tablename__ = "model"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)

    base_model_id = Column(Text, nullable=True)
    """
        An optional pointer to the actual model that should be used when proxying requests.
    """

    name = Column(Text)
    """
        The human-readable display name of the model.
    """

    params = Column(JSONField)
    """
        Holds a JSON encoded blob of parameters, see `ModelParams`.
    """

    meta = Column(JSONField)
    """
        Holds a JSON encoded blob of metadata, see `ModelMeta`.
    """

    access_control = Column(JSON, nullable=True)  # Controls data access levels.

    is_active = Column(Boolean, default=True)

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ModelModel(BaseModel):
    id: str
    user_id: str
    base_model_id: Optional[str] = None
    name: str
    params: ModelParams
    meta: ModelMeta
    access_control: Optional[dict] = None
    is_active: bool
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms (unchanged)
####################

class ModelUserResponse(ModelModel):
    user: Optional[UserResponse] = None


class ModelResponse(ModelModel):
    pass


class ModelForm(BaseModel):
    id: str
    base_model_id: Optional[str] = None
    name: str
    meta: ModelMeta
    params: ModelParams
    access_control: Optional[dict] = None
    is_active: bool = True


class ModelsTable:
    async def insert_new_model(
        self, form_data: ModelForm, user_id: str
    ) -> Optional[ModelModel]:
        model = ModelModel(
            **{
                **form_data.model_dump(),
                "user_id": user_id,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
        )
        try:
            async with get_db() as db:
                row = Model(**model.model_dump())
                db.add(row)
                await db.commit()
                await db.refresh(row)
                return ModelModel.model_validate(row) if row else None
        except Exception as e:
            log.exception(f"Failed to insert a new model: {e}")
            return None

    async def get_all_models(self) -> list[ModelModel]:
        async with get_db() as db:
            res = await db.execute(select(Model))
            return [ModelModel.model_validate(m) for m in res.scalars().all()]

    async def get_models(self) -> list[ModelUserResponse]:
        async with get_db() as db:
            # base_model_id != None -> use .is_not(None) in SQLAlchemy
            res = await db.execute(select(Model).where(Model.base_model_id.is_not(None)))
            rows = res.scalars().all()

        models: list[ModelUserResponse] = []
        for m in rows:
            # If Users.get_user_by_id has an async version, switch to: user = await Users.get_user_by_id(m.user_id)
            user = Users.get_user_by_id(m.user_id)
            models.append(
                ModelUserResponse.model_validate(
                    {
                        **ModelModel.model_validate(m).model_dump(),
                        "user": user.model_dump() if user else None,
                    }
                )
            )
        return models

    async def get_base_models(self) -> list[ModelModel]:
        async with get_db() as db:
            res = await db.execute(select(Model).where(Model.base_model_id.is_(None)))
            return [ModelModel.model_validate(m) for m in res.scalars().all()]

    async def get_models_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ModelUserResponse]:
        models = await self.get_models()
        return [
            model
            for model in models
            if model.user_id == user_id
            or has_access(user_id, permission, model.access_control)
        ]

    async def get_model_by_id(self, id: str) -> Optional[ModelModel]:
        try:
            async with get_db() as db:
                row = await db.get(Model, id)
                return ModelModel.model_validate(row) if row else None
        except Exception:
            return None

    async def toggle_model_by_id(self, id: str) -> Optional[ModelModel]:
        async with get_db() as db:
            try:
                row = await db.get(Model, id)
                if not row:
                    return None
                row.is_active = not bool(row.is_active)
                row.updated_at = int(time.time())
                await db.commit()
                await db.refresh(row)
                return ModelModel.model_validate(row)
            except Exception:
                return None

    async def update_model_by_id(self, id: str, model: ModelForm) -> Optional[ModelModel]:
        try:
            async with get_db() as db:
                row = await db.get(Model, id)
                if not row:
                    return None

                # update only fields present in form (excluding id)
                data = model.model_dump(exclude={"id"})
                for k, v in data.items():
                    setattr(row, k, v)
                row.updated_at = int(time.time())

                await db.commit()
                await db.refresh(row)
                return ModelModel.model_validate(row)
        except Exception as e:
            log.exception(f"Failed to update the model by id {id}: {e}")
            return None

    async def delete_model_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Model).where(Model.id == id))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_all_models(self) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Model))
                await db.commit()
                return True
        except Exception:
            return False


Models = ModelsTable()