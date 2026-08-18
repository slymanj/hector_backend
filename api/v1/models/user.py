from sqlalchemy import Column, String, Enum, Boolean
import enum
from api.v1.models.base_class import BaseModel
from sqlalchemy.orm import relationship


class UserRole(str, enum.Enum):
    """Platform roles for the crypto investment system.

    Must be str Enum so SQLAlchemy persists values ('investor'),
    not member names ('INVESTOR') — Postgres enum is lowercase.
    """

    INVESTOR = "investor"  # Can invest, connect wallets, view portfolio
    ADMIN = "admin"  # Full platform control, product verification
    FUND_MANAGER = "fund_manager"  # Create/manage investment products


class User(BaseModel):
    __tablename__ = "users"

    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    role = Column(
        Enum(
            UserRole,
            name="userrole",
            values_callable=lambda obj: [e.value for e in obj],
            validate_strings=True,
        ),
        nullable=False,
        default=UserRole.INVESTOR,
    )

    # Legacy primary Hedera address (kept for backward compatibility with
    # custodial HBAR flows). Prefer UserWallet rows for multi-chain access.
    wallet_address = Column(String(255), unique=True, nullable=True)
    encrypted_private_key = Column(String(500), nullable=True)

    is_verified = Column(Boolean, default=False, nullable=False)

    projects = relationship(
        "Project", back_populates="creator", cascade="all, delete-orphan"
    )
    investments = relationship(
        "Investment", back_populates="investor", cascade="all, delete-orphan"
    )
    organizations = relationship(
        "Organization", back_populates="creator", cascade="all, delete-orphan"
    )
    wallets = relationship(
        "UserWallet", back_populates="user", cascade="all, delete-orphan"
    )
