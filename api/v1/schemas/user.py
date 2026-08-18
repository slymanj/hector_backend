from pydantic import BaseModel, EmailStr, field_validator
from api.v1.models.user import UserRole
from typing import Optional
from datetime import datetime
from uuid import UUID
from api.utils.security import validate_password_strength


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    # Public self-registration is always investor. Admins/fund managers are promoted server-side.
    role: UserRole = UserRole.INVESTOR
    wallet_address: Optional[str] = None

    @field_validator("wallet_address")
    @classmethod
    def validate_wallet_address(cls, v):
        if v and not (
            v.startswith("0.0.")
            or v.startswith("0x")
            or v.startswith("bc1")
            or v.startswith("1")
            or v.startswith("3")
            or v.startswith("tb1")
        ):
            raise ValueError(
                "Invalid wallet address. Use Hedera (0.0.x), Ethereum (0x…), or Bitcoin formats."
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        validate_password_strength(v)
        return v

    @field_validator("role")
    @classmethod
    def block_privileged_self_register(cls, v: UserRole):
        # Public API always registers as investor (enforced again in service)
        if v != UserRole.INVESTOR:
            raise ValueError("Self-registration is limited to investor accounts")
        return v


class Login(BaseModel):
    email: EmailStr
    password: str


class ExportWalletRequest(BaseModel):
    """Password re-auth required before revealing custodial private key."""

    password: str


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    role: UserRole
    wallet_address: Optional[str] = None
    created_at: datetime
    is_verified: bool

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None and len(v.strip()) < 2:
            raise ValueError("Name must be at least 2 characters long")
        return v.strip() if v else v


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        validate_password_strength(v)
        return v


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        validate_password_strength(v)
        return v
