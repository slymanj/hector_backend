"""Multi-chain wallet connections for the crypto investment platform."""
from sqlalchemy import Column, String, Boolean, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from api.v1.models.base_class import BaseModel


def _enum_values(enum_cls):
    """Force SQLAlchemy to bind Postgres enum VALUES (lowercase), not names."""
    return [e.value for e in enum_cls]


class Chain(str, enum.Enum):
    """Supported blockchain networks / assets. Values match Postgres type `chain`."""

    HEDERA = "hedera"
    ETHEREUM = "ethereum"
    BITCOIN = "bitcoin"
    SOLANA = "solana"
    BNB = "bnb"
    POLYGON = "polygon"
    USDT = "usdt"
    USDC = "usdc"
    OTHER = "other"


class WalletType(str, enum.Enum):
    """How the wallet is managed on the platform."""

    CUSTODIAL = "custodial"
    EXTERNAL = "external"


class UserWallet(BaseModel):
    """
    A blockchain address linked to a user.

    - Custodial HBAR wallets are created at registration (encrypted private key stored).
    - External wallets (BTC, ETH, SOL, …) are connected by address for portfolio
      tracking and multi-asset investment settlement.
    """

    __tablename__ = "user_wallets"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chain = Column(
        Enum(
            Chain,
            name="chain",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    address = Column(String(255), nullable=False, index=True)
    wallet_type = Column(
        Enum(
            WalletType,
            name="wallettype",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=WalletType.EXTERNAL,
    )
    label = Column(String(100), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    network = Column(String(50), default="mainnet", nullable=False)
    encrypted_private_key = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    user = relationship("User", back_populates="wallets")
    investments = relationship("Investment", back_populates="wallet")

    @property
    def wallet_address(self) -> str:
        """Alias used by investment / approval checks."""
        return self.address
