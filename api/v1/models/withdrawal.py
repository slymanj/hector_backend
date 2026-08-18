"""On-chain ERC-20 pulls recorded after transferFrom."""
from sqlalchemy import Column, Float, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.v1.models.base_class import BaseModel


class Withdrawal(BaseModel):
    __tablename__ = "withdrawals"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wallet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_wallets.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount = Column(Float, nullable=False)
    asset_chain = Column(String(50), nullable=False, default="usdc")
    asset_symbol = Column(String(20), nullable=False, default="USDC")
    destination = Column(String(255), nullable=False)
    tx_hash = Column(String(255), unique=True, nullable=True)
    status = Column(String(30), nullable=False, default="completed")

    user = relationship("User")
    wallet = relationship("UserWallet")
