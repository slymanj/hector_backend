"""Investment records — capital committed by investors into products."""
from sqlalchemy import Column, Float, String, ForeignKey, Enum, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from api.v1.models.base_class import BaseModel


class InvestmentStatus(str, enum.Enum):
    pending = "pending"  # Awaiting on-chain confirmation (external wallets)
    completed = "completed"  # Funds settled / recorded
    active = "active"  # Position live, earning returns
    matured = "matured"  # Lock period ended
    withdrawn = "withdrawn"  # Principal (+ returns) paid out
    failed = "failed"
    cancelled = "cancelled"


class Investment(BaseModel):
    """
    An investor's capital commitment into an investment product.

    Settlement may be on-chain (Hedera HBAR via custodial wallet) or recorded
    against an externally connected wallet (BTC, ETH, etc.) with a tx hash.
    """

    __tablename__ = "investments"

    investor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wallet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_wallets.id", ondelete="SET NULL"),
        nullable=True,
    )

    amount = Column(Float, nullable=False)
    asset_chain = Column(String(50), nullable=False, default="hedera")  # Chain value
    asset_symbol = Column(String(20), nullable=False, default="HBAR")  # HBAR, BTC, ETH, USDT
    tx_hash = Column(String(255), unique=True, nullable=True)
    status = Column(
        Enum(
            InvestmentStatus,
            name="investmentstatus",
            values_callable=lambda obj: [e.value for e in obj],
            validate_strings=True,
        ),
        default=InvestmentStatus.pending,
        nullable=False,
    )

    expected_return_pct = Column(Float, nullable=True)  # snapshot of APY at invest time
    expected_payout = Column(Float, nullable=True)  # projected value at maturity
    lock_period_days = Column(Integer, nullable=True)
    maturity_date = Column(DateTime(timezone=True), nullable=True)
    onchain_id = Column(Integer, nullable=True)  # InvestmentPlatform.investments id

    investor = relationship("User", back_populates="investments")
    project = relationship("Project", back_populates="investments")
    wallet = relationship("UserWallet", back_populates="investments")
