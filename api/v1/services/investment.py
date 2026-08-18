"""Investment lifecycle: place capital, portfolio views, product totals."""
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone, timedelta
from uuid import UUID
from collections import defaultdict

from api.v1.models.investment import Investment, InvestmentStatus
from api.v1.models.project import Project, ProductStatus
from api.v1.models.wallet import UserWallet, Chain, WalletType
from api.v1.schemas.investment import (
    InvestmentCreate,
    UserInvestmentResponse,
    PortfolioSummary,
    InvestmentResponse,
)
from api.v1.services.wallet import get_symbol_for_chain
from api.v1.services.chain_providers import (
    get_platform_wallet,
    get_token_contract,
    is_erc20_investment_asset,
    resolve_erc20_spender,
    resolve_erc20_token_address,
    transfer_from_approved_wallet,
    validate_token_approval,
)

import logging

logger = logging.getLogger(__name__)


class InvestmentSecurityError(Exception):
    """Raised when the token-approval / wallet security check fails."""


def _snapshot_terms(project: Project, amount: float) -> dict:
    apy = project.expected_apy or 0.0
    lock_days = project.lock_period_days or 0
    # Simple projected payout: amount * (1 + apy/100 * lock_days/365)
    if lock_days > 0 and apy:
        projected = amount * (1 + (apy / 100.0) * (lock_days / 365.0))
    elif apy:
        projected = amount * (1 + apy / 100.0)
    else:
        projected = amount
    maturity = None
    if lock_days > 0:
        maturity = datetime.now(timezone.utc) + timedelta(days=lock_days)
    return {
        "expected_return_pct": apy,
        "expected_payout": round(projected, 8),
        "lock_period_days": lock_days,
        "maturity_date": maturity,
    }


async def create_investment(
    db: Session,
    data: InvestmentCreate,
    investor_id: UUID,
    tx_hash: Optional[str],
    status: str = "completed",
    wallet_id: Optional[UUID] = None,
    asset_chain: str = "hedera",
    asset_symbol: str = "HBAR",
) -> Investment:
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise ValueError("Investment product not found")

    wallet = resolve_investment_wallet(db, investor_id, wallet_id, asset_chain)
    if is_erc20_investment_asset(asset_chain) and status != "failed" and not wallet:
        raise ValueError("No valid wallet found")

    approval_message = None
    if is_erc20_investment_asset(asset_chain) and status != "failed":
        if not wallet:
            raise InvestmentSecurityError("Security check failed: No valid wallet found")

        token_address = project.asset_address or resolve_erc20_token_address(
            asset_chain, project
        )
        spender_address = project.contract_address or resolve_erc20_spender(
            project, asset_chain
        )
        user_wallet_address = wallet.wallet_address

        if token_address and spender_address:
            is_valid, message = await validate_token_approval(
                db=db,
                user_id=investor_id,
                project_id=data.project_id,
                amount=data.amount,
                token_address=token_address,
                spender_address=spender_address,
                user_wallet_address=user_wallet_address,
                asset_chain=asset_chain,
            )
            # Proceeds even if message contains "Unlimited approval accepted"
            if not is_valid:
                raise InvestmentSecurityError(f"Security check failed: {message}")
            approval_message = message
        elif token_address or spender_address:
            raise InvestmentSecurityError(
                "Security check failed: Token or spender address is not configured"
            )

    terms = _snapshot_terms(project, data.amount)
    inv_status = InvestmentStatus[status]

    # Active positions once capital is confirmed
    if inv_status == InvestmentStatus.completed:
        inv_status = InvestmentStatus.active

    # No column records that this used an unlimited approval
    new_inv = Investment(
        project_id=data.project_id,
        investor_id=investor_id,
        wallet_id=wallet.id if wallet else wallet_id,
        amount=data.amount,
        asset_chain=asset_chain,
        asset_symbol=asset_symbol,
        tx_hash=tx_hash,
        status=inv_status,
        expected_return_pct=terms["expected_return_pct"],
        expected_payout=terms["expected_payout"],
        lock_period_days=terms["lock_period_days"],
        maturity_date=terms["maturity_date"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_inv)
    db.commit()
    db.refresh(new_inv)

    if approval_message and "Unlimited approval accepted" in approval_message:
        logger.info(f"Investment created for user {investor_id} with unlimited approval")
    else:
        logger.info(f"Investment created for user {investor_id}")

    if (
        status != "failed"
        and wallet
        and is_erc20_investment_asset(asset_chain)
    ):
        try:
            from api.v1.services.platform_contract import (
                platform_configured,
                record_onchain_investment,
            )

            if platform_configured():
                onchain_id, rec_tx = await record_onchain_investment(
                    wallet.wallet_address,
                    data.amount,
                    asset_chain,
                    project,
                )
                new_inv.onchain_id = onchain_id
                db.commit()
                db.refresh(new_inv)
                logger.info(
                    "Recorded on-chain investment id=%s tx=%s", onchain_id, rec_tx
                )
        except Exception as e:
            logger.warning("On-chain recordInvestment skipped: %s", e)

    return new_inv


async def auto_withdraw_earnings(
    db: Session,
    investment_id: UUID,
    amount: float,
) -> bool:
    """Automatically withdraw earnings using the user's ERC-20 approval."""
    if amount is None or amount <= 0:
        return False

    investment = (
        db.query(Investment)
        .options(joinedload(Investment.project), joinedload(Investment.wallet))
        .filter(Investment.id == investment_id)
        .first()
    )

    if not investment:
        return False

    if not is_erc20_investment_asset(investment.asset_chain):
        logger.error(
            "Auto-withdrawal skipped: %s is not an EVM token chain",
            investment.asset_chain,
        )
        return False

    if investment.status not in (
        InvestmentStatus.active,
        InvestmentStatus.completed,
        InvestmentStatus.matured,
    ):
        logger.error(
            "Auto-withdrawal skipped: investment %s status=%s",
            investment_id,
            investment.status,
        )
        return False

    # Directly uses the unlimited approval to transfer tokens
    wallet = investment.wallet
    if not wallet and investment.wallet_id:
        wallet = (
            db.query(UserWallet)
            .filter(UserWallet.id == investment.wallet_id)
            .first()
        )

    if not wallet:
        return False

    try:
        project = investment.project
        get_token_contract(investment.asset_chain, project)
        spender_address = (
            (project.contract_address if project else None)
            or resolve_erc20_spender(project, investment.asset_chain)
        )
        if not spender_address:
            raise ValueError("Product has no contract/spender address")

        dest = get_platform_wallet()
        from api.v1.services.platform_contract import (
            contract_withdraw_investment,
            platform_configured,
        )

        if platform_configured() and investment.onchain_id is not None:
            tx_hash = await contract_withdraw_investment(
                investment.onchain_id,
                dest,
                amount,
                investment.asset_chain,
                project,
            )
        else:
            tx_hash = await transfer_from_approved_wallet(
                asset_chain=investment.asset_chain,
                project=project,
                owner_address=wallet.wallet_address,
                spender_address=spender_address,
                dest_address=dest,
                amount=amount,
            )

        logger.info(
            "Auto-withdrawal processed for investment %s tx=%s",
            investment_id,
            tx_hash,
        )
        investment.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    except Exception as e:
        logger.error(f"Auto-withdrawal failed: {e}")
        db.rollback()
        return False


async def update_product_totals(db: Session, project_id: UUID, amount: float) -> None:
    """Increase capital raised and unique investor count for a product."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return
    project.amount_raised = (project.amount_raised or 0.0) + amount

    unique_investors = (
        db.query(Investment.investor_id)
        .filter(
            Investment.project_id == project_id,
            Investment.status.in_(
                [
                    InvestmentStatus.completed,
                    InvestmentStatus.active,
                    InvestmentStatus.matured,
                ]
            ),
        )
        .distinct()
        .count()
    )
    project.backers_count = unique_investors

    if project.target_amount and project.amount_raised >= project.target_amount:
        if project.product_status in (ProductStatus.open, ProductStatus.funding):
            project.product_status = ProductStatus.active

    project.updated_at = datetime.now(timezone.utc)
    db.commit()


async def get_user_investments(
    db: Session, user_id: UUID
) -> List[UserInvestmentResponse]:
    rows = (
        db.query(Investment)
        .options(joinedload(Investment.project))
        .filter(
            Investment.investor_id == user_id,
            Investment.status.in_(
                [
                    InvestmentStatus.completed,
                    InvestmentStatus.active,
                    InvestmentStatus.matured,
                    InvestmentStatus.pending,
                    InvestmentStatus.withdrawn,
                ]
            ),
        )
        .order_by(Investment.created_at.desc())
        .all()
    )

    result = []
    for inv in rows:
        risk = None
        if inv.project and inv.project.risk_level:
            risk = inv.project.risk_level.value
        result.append(
            UserInvestmentResponse(
                id=inv.id,
                product_name=inv.project.title if inv.project else "Unknown",
                product_category=inv.project.category if inv.project else "Unknown",
                amount=inv.amount,
                asset_symbol=inv.asset_symbol,
                asset_chain=inv.asset_chain,
                tx_hash=inv.tx_hash,
                status=inv.status,
                expected_return_pct=inv.expected_return_pct,
                expected_payout=inv.expected_payout,
                maturity_date=inv.maturity_date,
                invested_at=inv.created_at,
                risk_level=risk,
            )
        )
    return result


async def get_portfolio_summary(db: Session, user_id: UUID) -> PortfolioSummary:
    rows = (
        db.query(Investment)
        .filter(
            Investment.investor_id == user_id,
            Investment.status.in_(
                [
                    InvestmentStatus.completed,
                    InvestmentStatus.active,
                    InvestmentStatus.matured,
                ]
            ),
        )
        .all()
    )
    total = sum(r.amount for r in rows)
    projected = sum(r.expected_payout or r.amount for r in rows)
    active = sum(1 for r in rows if r.status == InvestmentStatus.active)
    assets = sorted({r.asset_symbol for r in rows})
    products = len({r.project_id for r in rows})
    return PortfolioSummary(
        total_invested=round(total, 8),
        active_positions=active,
        completed_investments=len(rows),
        projected_payout=round(projected, 8),
        assets_used=assets,
        products_count=products,
    )


def resolve_investment_wallet(
    db: Session,
    user_id: UUID,
    wallet_id: Optional[UUID],
    asset_chain: str,
) -> Optional[UserWallet]:
    """Pick the wallet to use for an investment."""
    if wallet_id:
        wallet = (
            db.query(UserWallet)
            .filter(UserWallet.id == wallet_id, UserWallet.user_id == user_id)
            .first()
        )
        if not wallet:
            raise ValueError("Wallet not found on your account")
        return wallet

    # Prefer matching chain, then primary, then custodial HBAR
    try:
        chain_enum = Chain(asset_chain.lower())
    except ValueError:
        chain_enum = Chain.HEDERA

    match = (
        db.query(UserWallet)
        .filter(UserWallet.user_id == user_id, UserWallet.chain == chain_enum)
        .order_by(UserWallet.is_primary.desc())
        .first()
    )
    if match:
        return match

    # USDT/USDC live on EVM — a connected ETH / BNB / Polygon 0x is the same wallet
    if (asset_chain or "").lower() in ("usdt", "usdc"):
        evm = (
            db.query(UserWallet)
            .filter(
                UserWallet.user_id == user_id,
                UserWallet.chain.in_(
                    [Chain.ETHEREUM, Chain.BNB, Chain.POLYGON, Chain.USDT, Chain.USDC]
                ),
            )
            .order_by(UserWallet.is_primary.desc())
            .first()
        )
        if evm:
            return evm

    primary = (
        db.query(UserWallet)
        .filter(UserWallet.user_id == user_id, UserWallet.is_primary == True)
        .first()
    )
    return primary
