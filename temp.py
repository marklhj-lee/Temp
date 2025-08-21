import time
from typing import Optional

from open_webui.internal.db import Base, JSONField
from open_webui.internal.db_async import get_db  # ← async session

from open_webui.models.chats import Chats
from open_webui.models.groups import Groups

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, select, delete, select, func, or_


####################
# User DB Schema (unchanged)
####################

class User(Base):
    __tablename__ = "user"

    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String)
    role = Column(String)
    profile_image_url = Column(Text)

    last_active_at = Column(BigInteger)
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)

    api_key = Column(String, nullable=True, unique=True)
    settings = Column(JSONField, nullable=True)
    info = Column(JSONField, nullable=True)

    oauth_sub = Column(Text, unique=True)


class UserSettings(BaseModel):
    ui: Optional[dict] = {}
    model_config = ConfigDict(extra="allow")
    pass


class UserModel(BaseModel):
    id: str
    name: str
    email: str
    role: str = "pending"
    profile_image_url: str

    last_active_at: int  # timestamp in epoch
    updated_at: int
    created_at: int

    api_key: Optional[str] = None
    settings: Optional[UserSettings] = None
    info: Optional[dict] = None
    oauth_sub: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


####################
# Forms (unchanged)
####################

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    profile_image_url: str


class UserNameResponse(BaseModel):
    id: str
    name: str
    role: str
    profile_image_url: str


class UserRoleUpdateForm(BaseModel):
    id: str
    role: str


class UserUpdateForm(BaseModel):
    name: str
    email: str
    profile_image_url: str
    password: Optional[str] = None


class UsersTable:
    async def insert_new_user(
        self,
        id: str,
        name: str,
        email: str,
        profile_image_url: str = "/user.png",
        role: str = "pending",
        oauth_sub: Optional[str] = None,
    ) -> Optional[UserModel]:
        async with get_db() as db:
            user = UserModel(
                id=id,
                name=name,
                email=email,
                role=role,
                profile_image_url=profile_image_url,
                last_active_at=int(time.time()),
                created_at=int(time.time()),
                updated_at=int(time.time()),
                oauth_sub=oauth_sub,
            )
            row = User(**user.model_dump())
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return user if row else None

    async def get_user_by_id(self, id: str) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                return UserModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_user_by_api_key(self, api_key: str) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                res = await db.execute(select(User).filter_by(api_key=api_key))
                row = res.scalars().first()
                return UserModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_user_by_email(self, email: str) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                res = await db.execute(select(User).filter_by(email=email))
                row = res.scalars().first()
                return UserModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_user_by_oauth_sub(self, sub: str) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                res = await db.execute(select(User).filter_by(oauth_sub=sub))
                row = res.scalars().first()
                return UserModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_users(
        self,
        filter: Optional[dict] = None,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict:
        async with get_db() as db:
            query = select(User)

            if filter:
                query_key = filter.get("query")
                if query_key:
                    query = query.where(
                        or_(
                            User.name.ilike(f"%{query_key}%"),
                            User.email.ilike(f"%{query_key}%"),
                        )
                    )

                order_by = filter.get("order_by")
                direction = filter.get("direction")

                if order_by == "name":
                    query = query.order_by(
                        User.name.asc() if direction == "asc" else User.name.desc()
                    )
                elif order_by == "email":
                    query = query.order_by(
                        User.email.asc() if direction == "asc" else User.email.desc()
                    )
                elif order_by == "created_at":
                    query = query.order_by(
                        User.created_at.asc() if direction == "asc" else User.created_at.desc()
                    )
                elif order_by == "last_active_at":
                    query = query.order_by(
                        User.last_active_at.asc() if direction == "asc" else User.last_active_at.desc()
                    )
                elif order_by == "updated_at":
                    query = query.order_by(
                        User.updated_at.asc() if direction == "asc" else User.updated_at.desc()
                    )
                elif order_by == "role":
                    query = query.order_by(
                        User.role.asc() if direction == "asc" else User.role.desc()
                    )
            else:
                query = query.order_by(User.created_at.desc())

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)

            # fetch users
            res = await db.execute(query)
            users = res.scalars().all()

            # fetch total count
            total_res = await db.execute(select(func.count()).select_from(User))
            total = total_res.scalar()

            return {
                "users": [UserModel.model_validate(user) for user in users],
                "total": total,
            }

    async def get_users_by_user_ids(self, user_ids: list[str]) -> list[UserModel]:
        async with get_db() as db:
            res = await db.execute(select(User).where(User.id.in_(user_ids)))
            return [UserModel.model_validate(u) for u in res.scalars().all()]

    async def get_num_users(self) -> Optional[int]:
        async with get_db() as db:
            res = await db.execute(select(User))
            return len(res.scalars().all())

    async def get_first_user(self) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                res = await db.execute(select(User).order_by(User.created_at))
                row = res.scalars().first()
                return UserModel.model_validate(row) if row else None
        except Exception:
            return None

    async def get_user_webhook_url_by_id(self, id: str) -> Optional[str]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row or row.settings is None:
                    return None
                return row.settings.get("ui", {}).get("notifications", {}).get("webhook_url")
        except Exception:
            return None

    async def update_user_role_by_id(self, id: str, role: str) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return None
                row.role = role
                await db.commit()
                await db.refresh(row)
                return UserModel.model_validate(row)
        except Exception:
            return None

    async def update_user_profile_image_url_by_id(
        self, id: str, profile_image_url: str
    ) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return None
                row.profile_image_url = profile_image_url
                await db.commit()
                await db.refresh(row)
                return UserModel.model_validate(row)
        except Exception:
            return None

    async def update_user_last_active_by_id(self, id: str) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return None
                row.last_active_at = int(time.time())
                await db.commit()
                await db.refresh(row)
                return UserModel.model_validate(row)
        except Exception:
            return None

    async def update_user_oauth_sub_by_id(
        self, id: str, oauth_sub: str
    ) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return None
                row.oauth_sub = oauth_sub
                await db.commit()
                await db.refresh(row)
                return UserModel.model_validate(row)
        except Exception:
            return None

    async def update_user_by_id(self, id: str, updated: dict) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return None
                for k, v in updated.items():
                    setattr(row, k, v)
                await db.commit()
                await db.refresh(row)
                return UserModel.model_validate(row)
        except Exception:
            return None

    async def update_user_settings_by_id(self, id: str, updated: dict) -> Optional[UserModel]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return None
                settings = row.settings or {}
                settings.update(updated)
                row.settings = settings
                await db.commit()
                await db.refresh(row)
                return UserModel.model_validate(row)
        except Exception:
            return None

    async def delete_user_by_id(self, id: str) -> bool:
        try:
            # Remove User from Groups
            await Groups.remove_user_from_all_groups(id)

            # Delete User Chats
            result = await Chats.delete_chats_by_user_id(id)
            if result:
                async with get_db() as db:
                    await db.execute(delete(User).where(User.id == id))
                    await db.commit()
                return True
            return False
        except Exception:
            return False

    async def update_user_api_key_by_id(self, id: str, api_key: str) -> bool:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                if not row:
                    return False
                row.api_key = api_key
                await db.commit()
                return True
        except Exception:
            return False

    async def get_user_api_key_by_id(self, id: str) -> Optional[str]:
        try:
            async with get_db() as db:
                row = await db.get(User, id)
                return row.api_key if row else None
        except Exception:
            return None

    async def get_valid_user_ids(self, user_ids: list[str]) -> list[str]:
        async with get_db() as db:
            res = await db.execute(select(User).where(User.id.in_(user_ids)))
            return [u.id for u in res.scalars().all()]


Users = UsersTable()
