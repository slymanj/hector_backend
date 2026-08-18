from pydantic import BaseModel, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional
from api.v1.models.investment import InvestmentStatus


class InvestmentCreate(BaseModel):
    """Place capital into an investment product."""

    project_id: UUID
    amount: float
    # Optional: which connected wallet / asset to use
    wallet_id: Optional[UUID] = None
    asset_chain: Optional[str] = "hedera"
    asset_symbol: Optional[str] = "HBAR"
    # For external-wallet investments, client may submit a known tx hash
    tx_hash: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Investment amount must be greater than 0")
        return v


class InvestmentResponse(BaseModel):
    id: UUID
    project_id: UUID
    investor_id: UUID
    wallet_id: Optional[UUID] = None
    amount: float
    asset_chain: str
    asset_symbol: str
    tx_hash: Optional[str] = None
    status: InvestmentStatus
    expected_return_pct: Optional[float] = None
    expected_payout: Optional[float] = None
    lock_period_days: Optional[int] = None
    maturity_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserInvestmentResponse(BaseModel):
    id: UUID
    product_name: str
    product_category: str
    amount: float
    asset_symbol: str
    asset_chain: str
    tx_hash: Optional[str]
    status: InvestmentStatus
    expected_return_pct: Optional[float]
    expected_payout: Optional[float]
    maturity_date: Optional[datetime]
    invested_at: datetime
    risk_level: Optional[str] = None

    class Config:
        from_attributes = True


class PortfolioSummary(BaseModel):
    total_invested: float
    active_positions: int
    completed_investments: int
    projected_payout: float
    assets_used: list
    products_count: int


class ApprovalCheckRequest(BaseModel):
    project_id: UUID
    amount: float
    asset_chain: str
    wallet_id: Optional[UUID] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class ApprovalCheckResponse(BaseModel):
    valid: bool
    message: str
    token_address: Optional[str] = None
    spender_address: Optional[str] = None
    user_wallet_address: Optional[str] = None
    asset_chain: str
    amount: float
    unlimited_accepted: bool = True


class AutoWithdrawRequest(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Withdrawal amount must be greater than 0")
        return v


class AutoWithdrawResponse(BaseModel):
    success: bool
    investment_id: UUID
    amount: float
    message: str


class InvestmentCreatedResponse(BaseModel):
    status: str
    investment_id: UUID
    message: str
