from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from api.db.database import get_db
from api.v1.services.auth import get_current_user
from api.v1.models.user import User
from api.v1.models.wallet import Chain, WalletType
from api.v1.schemas.wallet import (
    WalletConnect,
    WalletUpdate,
    WalletResponse,
    WalletBalanceResponse,
    SupportedChainInfo,
)
from api.v1.services.wallet import (
    connect_wallet,
    list_user_wallets,
    update_wallet,
    disconnect_wallet,
    set_primary_wallet,
    SUPPORTED_CHAINS_CATALOG,
    get_symbol_for_chain,
    get_wallet,
)
from api.v1.services.chain_providers import fetch_chain_balance, get_network_status
from api.utils.settings import settings

router = APIRouter(prefix="/wallets", tags=["wallets"])


@router.get("/supported-chains", response_model=List[SupportedChainInfo])
async def list_supported_chains():
    """List blockchains enabled in ENABLED_CHAINS (from .env)."""
    enabled = set(settings.enabled_chains_list)
    catalog = [SupportedChainInfo(**c) for c in SUPPORTED_CHAINS_CATALOG if c["chain"] in enabled]
    return catalog


@router.get("/network-status")
async def network_status():
    """
    Show which chains are enabled and whether RPC/API env vars are configured.

    Use this to verify .env multi-chain setup without calling balances.
    """
    return get_network_status()


@router.post("/connect", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
async def connect_external_wallet(
    payload: WalletConnect,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Connect an external wallet (Bitcoin, Ethereum, Solana, USDT, etc.).

    Custodial Hedera wallets are created automatically at registration.
    """
    try:
        return await connect_wallet(db, current_user, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[WalletResponse])
async def get_my_wallets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all wallets linked to the authenticated investor."""
    return await list_user_wallets(db, current_user.id)


@router.get("/{wallet_id}", response_model=WalletResponse)
async def get_wallet_detail(
    wallet_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        wallet = await get_wallet(db, wallet_id, current_user.id)
        from api.v1.services.wallet import wallet_to_response

        return wallet_to_response(wallet)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{wallet_id}", response_model=WalletResponse)
async def patch_wallet(
    wallet_id: UUID,
    payload: WalletUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await update_wallet(db, wallet_id, current_user.id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{wallet_id}/primary", response_model=WalletResponse)
async def make_primary(
    wallet_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await set_primary_wallet(db, wallet_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{wallet_id}")
async def remove_wallet(
    wallet_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        await disconnect_wallet(db, wallet_id, current_user.id)
        return {"message": "Wallet disconnected"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{wallet_id}/balance", response_model=WalletBalanceResponse)
async def wallet_balance(
    wallet_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch on-chain balance using providers configured in .env.

    - Hedera: operator credentials (HEDERA_*)
    - Ethereum / BNB / Polygon: *_RPC_URL
    - Bitcoin: BITCOIN_API_URL (Blockstream-compatible)
    - Solana: SOLANA_RPC_URL
    - USDT / USDC: contract address + STABLECOIN_RPC_SOURCE RPC
    """
    try:
        wallet = await get_wallet(db, wallet_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    result = await fetch_chain_balance(wallet.chain, wallet.address)
    return WalletBalanceResponse(
        wallet_id=wallet.id,
        chain=wallet.chain,
        address=wallet.address,
        balance=result.get("balance"),
        symbol=result.get("symbol") or get_symbol_for_chain(wallet.chain),
        note=result.get("note"),
    )
