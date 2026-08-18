"""Investment products offered on the platform (legacy table name: projects)."""
from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from api.v1.models.base_class import BaseModel


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    very_high = "very_high"


class ProductStatus(str, enum.Enum):
    draft = "draft"
    open = "open"  # Accepting investments
    funding = "funding"  # Actively raising capital
    active = "active"  # Fully deployed / generating returns
    closed = "closed"  # No longer accepting capital
    matured = "matured"  # Product term completed


class Project(BaseModel):
    """
    An investment product (pool, fund, yield opportunity, or venture raise).
    Table name: `projects`.
    """

    __tablename__ = "projects"

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)  # e.g. DeFi, Real Estate, RWA, Staking

    target_amount = Column(Float, nullable=False)
    amount_raised = Column(Float, default=0.0)  # total capital invested
    backers_count = Column(Integer, default=0)  # unique investors (legacy column name)

    # Investment-specific terms
    expected_apy = Column(Float, nullable=True)  # expected annual % yield
    risk_level = Column(
        Enum(
            RiskLevel,
            name="risklevel",
            values_callable=lambda obj: [e.value for e in obj],
            validate_strings=True,
        ),
        default=RiskLevel.medium,
        nullable=False,
    )
    min_investment = Column(Float, default=1.0, nullable=False)
    lock_period_days = Column(Integer, default=0, nullable=False)
    product_status = Column(
        Enum(
            ProductStatus,
            name="productstatus",
            values_callable=lambda obj: [e.value for e in obj],
            validate_strings=True,
        ),
        default=ProductStatus.open,
        nullable=False,
    )
    # Comma-separated Chain values, e.g. "hedera,ethereum,bitcoin,usdt"
    accepted_assets = Column(String(255), default="hedera", nullable=False)
    settlement_currency = Column(String(20), default="HBAR", nullable=False)

    location = Column(String(255), nullable=True)
    verified = Column(Boolean, default=False)
    wallet_address = Column(String(255), nullable=False)  # primary treasury (Hedera)
    # Optional JSON-like string of extra treasury addresses: {"ethereum":"0x...","bitcoin":"bc1..."}
    treasury_addresses = Column(Text, nullable=True)
    # ERC-20 token the product settles in (WETH / USDT / USDC / …)
    asset_address = Column(String(255), nullable=True)
    # Spender the investor must approve (vault / product contract / treasury)
    contract_address = Column(String(255), nullable=True)

    image = Column(LargeBinary, nullable=True)
    image_mime_type = Column(String(50), nullable=True)

    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    creator = relationship("User", back_populates="projects")
    investments = relationship(
        "Investment", back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def total_invested(self) -> float:
        return self.amount_raised or 0.0

    @property
    def investors_count(self) -> int:
        return self.backers_count or 0

    @property
    def accepted_assets_list(self) -> list:
        if not self.accepted_assets:
            return ["hedera"]
        return [a.strip() for a in self.accepted_assets.split(",") if a.strip()]
