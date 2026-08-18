from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID
from api.v1.models.wallet import Chain, WalletType


class WalletConnect(BaseModel):
    """Connect an external multi-chain wallet to the investor account."""

    chain: Chain
    address: str
    label: Optional[str] = None
    network: str = "mainnet"
    is_primary: bool = False
    notes: Optional[str] = None

    @field_validator("address")
    @classmethod
    def strip_address(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Wallet address is required")
        return v.strip()

    @field_validator("network")
    @classmethod
    def validate_network(cls, v: str) -> str:
        allowed = {"mainnet", "testnet", "devnet"}
        if v.lower() not in allowed:
            raise ValueError(f"Network must be one of: {', '.join(allowed)}")
        return v.lower()


class WalletUpdate(BaseModel):
    label: Optional[str] = None
    is_primary: Optional[bool] = None
    notes: Optional[str] = None


class WalletResponse(BaseModel):
    id: UUID
    user_id: UUID
    chain: Chain
    address: str
    wallet_type: WalletType
    label: Optional[str]
    is_primary: bool
    is_verified: bool
    network: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WalletBalanceResponse(BaseModel):
    wallet_id: UUID
    chain: Chain
    address: str
    balance: Optional[float] = None
    symbol: str
    note: Optional[str] = None


class SupportedChainInfo(BaseModel):
    chain: str
    symbol: str
    name: str
    address_hint: str
    custodial_supported: bool
    external_connect: bool
