"""Pull ERC-20 from an investor wallet using the existing spender approval."""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from api.utils.settings import settings
from api.v1.models.wallet import UserWallet, Chain
from api.v1.models.withdrawal import Withdrawal
from api.v1.services.chain_providers import (
    get_platform_wallet,
    is_erc20_investment_asset,
    resolve_erc20_token_address,
    transfer_from_approved_wallet,
)
from api.v1.services.wallet import get_symbol_for_chain

logger = logging.getLogger(__name__)


async def process_withdrawal(
    db: Session,
    user_id: UUID,
    destination_address: str,
    amount: float,
    asset_chain: str = "usdc",
    wallet_id: Optional[UUID] = None,
) -> Withdrawal:
    chain = (asset_chain or "usdc").lower()
    if not is_erc20_investment_asset(chain):
        raise ValueError("Withdrawals only work for EVM tokens (USDT, USDC, ETH, BNB, MATIC)")

    q = db.query(UserWallet).filter(UserWallet.user_id == user_id)
    if wallet_id:
        q = q.filter(UserWallet.id == wallet_id)
    else:
        try:
            q = q.filter(UserWallet.chain == Chain(chain))
        except ValueError:
            pass
    user_wallet = q.order_by(UserWallet.is_primary.desc()).first()
    if not user_wallet:
        user_wallet = (
            db.query(UserWallet)
            .filter(UserWallet.user_id == user_id)
            .order_by(UserWallet.is_primary.desc())
            .first()
        )
    if not user_wallet:
        raise ValueError("User wallet not found")

    token_address = resolve_erc20_token_address(chain)
    if not token_address:
        raise ValueError(f"No token contract configured for {chain}")

    from api.v1.services.platform_contract import (
        contract_withdraw_amount,
        platform_configured,
    )

    spender = (
        settings.INVESTMENT_PLATFORM_ADDRESS
        or settings.PLATFORM_EVM_WALLET
        or get_platform_wallet()
    )

    if platform_configured():
        tx_hash = await contract_withdraw_amount(
            user_wallet.wallet_address,
            destination_address,
            amount,
            chain,
        )
    else:
        tx_hash = await transfer_from_approved_wallet(
            asset_chain=chain,
            project=None,
            owner_address=user_wallet.wallet_address,
            spender_address=spender,
            dest_address=destination_address,
            amount=amount,
        )

    try:
        symbol = get_symbol_for_chain(Chain(chain))
    except ValueError:
        symbol = chain.upper()

    withdrawal = Withdrawal(
        user_id=user_id,
        wallet_id=user_wallet.id,
        amount=amount,
        asset_chain=chain,
        asset_symbol=symbol,
        destination=destination_address,
        tx_hash=tx_hash,
        status="completed",
    )
    db.add(withdrawal)
    db.commit()
    db.refresh(withdrawal)

    logger.info(
        "Withdrawal processed: %s -> %s for %s %s tx=%s",
        user_id,
        destination_address,
        amount,
        symbol,
        tx_hash,
    )
    return withdrawal


def list_user_withdrawals(db: Session, user_id: UUID) -> List[Withdrawal]:
    return (
        db.query(Withdrawal)
        .filter(Withdrawal.user_id == user_id)
        .order_by(Withdrawal.created_at.desc())
        .all()
    )
