"""Multi-chain wallet connect / manage service."""
import re
import logging
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from api.utils.settings import settings
from api.v1.models.wallet import UserWallet, Chain, WalletType
from api.v1.models.user import User
from api.v1.schemas.wallet import WalletConnect, WalletUpdate, WalletResponse

logger = logging.getLogger(__name__)

# Address format validators per chain
ADDRESS_PATTERNS = {
    Chain.HEDERA: re.compile(r"^0\.0\.\d+$"),
    Chain.ETHEREUM: re.compile(r"^0x[a-fA-F0-9]{40}$"),
    Chain.POLYGON: re.compile(r"^0x[a-fA-F0-9]{40}$"),
    Chain.BNB: re.compile(r"^0x[a-fA-F0-9]{40}$"),
    Chain.USDT: re.compile(r"^0x[a-fA-F0-9]{40}$"),
    Chain.USDC: re.compile(r"^0x[a-fA-F0-9]{40}$"),
    # Bitcoin: legacy (1/3) or bech32 (bc1)
    Chain.BITCOIN: re.compile(
        r"^(bc1[a-zA-HJ-NP-Z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$"
    ),
    # Solana base58, 32–44 chars
    Chain.SOLANA: re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"),
    Chain.OTHER: re.compile(r"^.{8,255}$"),
}

CHAIN_SYMBOLS = {
    Chain.HEDERA: "HBAR",
    Chain.ETHEREUM: "ETH",
    Chain.BITCOIN: "BTC",
    Chain.SOLANA: "SOL",
    Chain.BNB: "BNB",
    Chain.POLYGON: "MATIC",
    Chain.USDT: "USDT",
    Chain.USDC: "USDC",
    Chain.OTHER: "CRYPTO",
}

SUPPORTED_CHAINS_CATALOG = [
    {
        "chain": "hedera",
        "symbol": "HBAR",
        "name": "Hedera",
        "address_hint": "0.0.xxxxx",
        "custodial_supported": True,
        "external_connect": True,
    },
    {
        "chain": "ethereum",
        "symbol": "ETH",
        "name": "Ethereum",
        "address_hint": "0x… (40 hex chars)",
        "custodial_supported": False,
        "external_connect": True,
    },
    {
        "chain": "bitcoin",
        "symbol": "BTC",
        "name": "Bitcoin",
        "address_hint": "bc1… / 1… / 3…",
        "custodial_supported": False,
        "external_connect": True,
    },
    {
        "chain": "solana",
        "symbol": "SOL",
        "name": "Solana",
        "address_hint": "Base58 public key",
        "custodial_supported": False,
        "external_connect": True,
    },
    {
        "chain": "bnb",
        "symbol": "BNB",
        "name": "BNB Smart Chain",
        "address_hint": "0x… (EVM)",
        "custodial_supported": False,
        "external_connect": True,
    },
    {
        "chain": "polygon",
        "symbol": "MATIC",
        "name": "Polygon",
        "address_hint": "0x… (EVM)",
        "custodial_supported": False,
        "external_connect": True,
    },
    {
        "chain": "usdt",
        "symbol": "USDT",
        "name": "Tether (USDT)",
        "address_hint": "0x… ERC-20 style address",
        "custodial_supported": False,
        "external_connect": True,
    },
    {
        "chain": "usdc",
        "symbol": "USDC",
        "name": "USD Coin",
        "address_hint": "0x… ERC-20 style address",
        "custodial_supported": False,
        "external_connect": True,
    },
]


def validate_address_for_chain(chain: Chain, address: str) -> None:
    pattern = ADDRESS_PATTERNS.get(chain, ADDRESS_PATTERNS[Chain.OTHER])
    if not pattern.match(address):
        hint = next(
            (c["address_hint"] for c in SUPPORTED_CHAINS_CATALOG if c["chain"] == chain.value),
            "valid address for this chain",
        )
        raise ValueError(f"Invalid {chain.value} address format. Expected: {hint}")


def wallet_to_response(wallet: UserWallet) -> WalletResponse:
    return WalletResponse(
        id=wallet.id,
        user_id=wallet.user_id,
        chain=wallet.chain,
        address=wallet.address,
        wallet_type=wallet.wallet_type,
        label=wallet.label,
        is_primary=wallet.is_primary,
        is_verified=wallet.is_verified,
        network=wallet.network,
        notes=wallet.notes,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
    )


async def connect_wallet(
    db: Session, user: User, data: WalletConnect
) -> WalletResponse:
    """Link an external wallet address to the user."""
    if not settings.is_chain_enabled(data.chain.value):
        raise ValueError(
            f"Chain '{data.chain.value}' is disabled. "
            f"Enabled: {', '.join(settings.enabled_chains_list)}. "
            "Update ENABLED_CHAINS in .env."
        )

    validate_address_for_chain(data.chain, data.address)

    # Prefer env network labels when client omits / uses default
    network = data.network
    if data.chain == Chain.ETHEREUM and data.network in ("mainnet", "testnet"):
        network = settings.ETHEREUM_NETWORK
    elif data.chain == Chain.BITCOIN and data.network in ("mainnet", "testnet"):
        network = settings.BITCOIN_NETWORK
    elif data.chain == Chain.SOLANA and data.network in ("mainnet", "testnet", "devnet"):
        network = settings.SOLANA_NETWORK
    elif data.chain == Chain.BNB:
        network = settings.BNB_NETWORK
    elif data.chain == Chain.POLYGON:
        network = settings.POLYGON_NETWORK

    existing = (
        db.query(UserWallet)
        .filter(
            UserWallet.user_id == user.id,
            UserWallet.chain == data.chain,
            UserWallet.address == data.address,
        )
        .first()
    )
    if existing:
        raise ValueError("This wallet is already connected to your account")

    # Prevent another user claiming same chain+address
    claimed = (
        db.query(UserWallet)
        .filter(UserWallet.chain == data.chain, UserWallet.address == data.address)
        .first()
    )
    if claimed:
        raise ValueError("This wallet address is already linked to another account")

    if data.is_primary:
        db.query(UserWallet).filter(
            UserWallet.user_id == user.id, UserWallet.is_primary == True
        ).update({"is_primary": False})

    wallet = UserWallet(
        user_id=user.id,
        chain=data.chain,
        address=data.address,
        wallet_type=WalletType.EXTERNAL,
        label=data.label or f"{data.chain.value.upper()} wallet",
        is_primary=data.is_primary,
        is_verified=not settings.REQUIRE_WALLET_SIGNATURE,  # soft-verify unless required
        network=network,
        notes=data.notes,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    logger.info(f"User {user.id} connected {data.chain.value} wallet {data.address}")
    return wallet_to_response(wallet)


async def ensure_custodial_hedera_wallet(
    db: Session,
    user: User,
    address: str,
    encrypted_private_key: str,
) -> UserWallet:
    """Create / sync the platform custodial Hedera wallet row after registration."""
    existing = (
        db.query(UserWallet)
        .filter(
            UserWallet.user_id == user.id,
            UserWallet.chain == Chain.HEDERA,
            UserWallet.wallet_type == WalletType.CUSTODIAL,
        )
        .first()
    )
    if existing:
        return existing

    wallet = UserWallet(
        user_id=user.id,
        chain=Chain.HEDERA,
        address=address,
        wallet_type=WalletType.CUSTODIAL,
        label="Platform HBAR wallet",
        is_primary=True,
        is_verified=True,
        network="testnet",  # overridden by settings in production use
        encrypted_private_key=encrypted_private_key,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


async def list_user_wallets(db: Session, user_id: UUID) -> List[WalletResponse]:
    wallets = (
        db.query(UserWallet)
        .filter(UserWallet.user_id == user_id)
        .order_by(UserWallet.is_primary.desc(), UserWallet.created_at.desc())
        .all()
    )
    return [wallet_to_response(w) for w in wallets]


async def get_wallet(db: Session, wallet_id: UUID, user_id: UUID) -> UserWallet:
    wallet = (
        db.query(UserWallet)
        .filter(UserWallet.id == wallet_id, UserWallet.user_id == user_id)
        .first()
    )
    if not wallet:
        raise ValueError("Wallet not found")
    return wallet


async def update_wallet(
    db: Session, wallet_id: UUID, user_id: UUID, data: WalletUpdate
) -> WalletResponse:
    wallet = await get_wallet(db, wallet_id, user_id)
    payload = data.model_dump(exclude_unset=True)

    if payload.get("is_primary") is True:
        db.query(UserWallet).filter(
            UserWallet.user_id == user_id, UserWallet.is_primary == True
        ).update({"is_primary": False})

    for field, value in payload.items():
        setattr(wallet, field, value)
    wallet.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wallet)
    return wallet_to_response(wallet)


async def disconnect_wallet(db: Session, wallet_id: UUID, user_id: UUID) -> bool:
    wallet = await get_wallet(db, wallet_id, user_id)
    if wallet.wallet_type == WalletType.CUSTODIAL:
        raise ValueError(
            "Cannot disconnect the platform custodial wallet. Export keys from profile instead."
        )
    db.delete(wallet)
    db.commit()
    return True


async def set_primary_wallet(
    db: Session, wallet_id: UUID, user_id: UUID
) -> WalletResponse:
    wallet = await get_wallet(db, wallet_id, user_id)
    db.query(UserWallet).filter(
        UserWallet.user_id == user_id, UserWallet.is_primary == True
    ).update({"is_primary": False})
    wallet.is_primary = True
    wallet.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wallet)
    return wallet_to_response(wallet)


def get_symbol_for_chain(chain: Chain) -> str:
    return CHAIN_SYMBOLS.get(chain, "CRYPTO")
