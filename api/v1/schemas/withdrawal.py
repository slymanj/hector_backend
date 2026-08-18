from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class WithdrawRequest(BaseModel):
    destination_address: str
    amount: float
    asset_chain: str = "usdc"
    wallet_id: Optional[UUID] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v

    @field_validator("destination_address")
    @classmethod
    def evm_destination(cls, v: str) -> str:
        addr = (v or "").strip()
        if not addr.startswith("0x") or len(addr) != 42:
            raise ValueError("destination_address must be a 0x EVM address")
        return addr


class WithdrawResponse(BaseModel):
    status: str
    message: str
    tx_hash: Optional[str] = None
    withdrawal_id: Optional[UUID] = None
    amount: float
    destination: str


class WithdrawalRecord(BaseModel):
    id: UUID
    user_id: UUID
    amount: float
    asset_chain: str
    asset_symbol: str
    destination: str
    tx_hash: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
