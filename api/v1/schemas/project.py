from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from api.v1.models.project import RiskLevel, ProductStatus


class ProjectCreate(BaseModel):
    """Create an investment product."""

    title: str
    description: str
    category: str
    target_amount: float
    location: Optional[str] = None
    verified: bool = False
    expected_apy: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.medium
    min_investment: float = 1.0
    lock_period_days: int = 0
    product_status: ProductStatus = ProductStatus.open
    accepted_assets: Optional[str] = "hedera"  # comma-separated chains
    settlement_currency: str = "HBAR"
    treasury_addresses: Optional[str] = None  # JSON string of chain->address
    asset_address: Optional[str] = None  # ERC-20 token contract
    contract_address: Optional[str] = None  # spender / vault the user approves

    @field_validator("target_amount")
    @classmethod
    def target_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Target amount must be greater than 0")
        return v

    @field_validator("min_investment")
    @classmethod
    def min_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Minimum investment cannot be negative")
        return v


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    description: str
    category: str
    target_amount: float
    amount_raised: float  # total capital invested
    backers_count: int  # investors count
    # Investment fields
    expected_apy: Optional[float] = None
    risk_level: Optional[RiskLevel] = None
    min_investment: Optional[float] = None
    lock_period_days: Optional[int] = None
    product_status: Optional[ProductStatus] = None
    accepted_assets: Optional[str] = None
    settlement_currency: Optional[str] = None
    treasury_addresses: Optional[str] = None
    asset_address: Optional[str] = None
    contract_address: Optional[str] = None
    location: Optional[str]
    verified: bool
    wallet_address: str
    image: Optional[str] = None
    image_mime_type: Optional[str] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    # Convenience aliases for investment terminology
    total_invested: Optional[float] = None
    investors_count: Optional[int] = None
    funding_progress_pct: Optional[float] = None

    class Config:
        from_attributes = True


class ProjectDB(BaseModel):
    id: UUID
    title: str
    description: str
    category: str
    target_amount: float
    amount_raised: float
    backers_count: int
    expected_apy: Optional[float] = None
    risk_level: Optional[RiskLevel] = None
    min_investment: Optional[float] = None
    lock_period_days: Optional[int] = None
    product_status: Optional[ProductStatus] = None
    accepted_assets: Optional[str] = None
    settlement_currency: Optional[str] = None
    treasury_addresses: Optional[str] = None
    asset_address: Optional[str] = None
    contract_address: Optional[str] = None
    location: Optional[str]
    verified: bool
    wallet_address: str
    image: Optional[bytes] = None
    image_mime_type: Optional[str] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
