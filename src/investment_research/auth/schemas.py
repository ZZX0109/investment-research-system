from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from investment_research.domain.models import User


class RegisterRequest(BaseModel):
    email: str
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email address")
        return normalized


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email address")
        return normalized


class TokenBundle(BaseModel):
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class AuthResponse(BaseModel):
    user: User
    access_expires_at: datetime
    refresh_expires_at: datetime
