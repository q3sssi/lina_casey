from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class LoginIn(BaseModel):
    username: str
    password: str = Field(max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def _norm_username(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class RegisterIn(LoginIn):
    username: str = Field(pattern=r"^[a-z0-9_]{3,32}$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode()) > 72:  # лимит bcrypt — 72 байта
            raise ValueError("password is too long (max 72 bytes)")
        return v

    @field_validator("username")
    @classmethod
    def _reserved(cls, v: str) -> str:
        if v in {"me", "admin", "api"}:
            raise ValueError("username is reserved")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    bio: str
    avatar_url: str | None
    created_at: datetime


Text1000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Text2000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    avatar_url: str | None


class ProfileUpdate(BaseModel):
    bio: Text1000


class PostIn(BaseModel):
    text: Text2000


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int
    text: str
    created_at: datetime
    author: UserBrief
