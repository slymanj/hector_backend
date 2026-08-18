from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import logging

from api.db.database import get_db
from api.v1.services.hedera import (
    invest_hbar_from_user,
    get_wallet_balance,
)
from api.v1.services.investment import (
    create_investment,
    get_user_investments,
    get_portfolio_summary,
    update_product_totals,
    resolve_investment_wallet,
    auto_withdraw_earnings,
    InvestmentSecurityError,
)
from api.v1.schemas.investment import (
    InvestmentCreate,
    InvestmentResponse,
    UserInvestmentResponse,
    PortfolioSummary,
    ApprovalCheckRequest,
    ApprovalCheckResponse,
    AutoWithdrawRequest,
    AutoWithdrawResponse,
    InvestmentCreatedResponse,
)
from api.v1.models.project import Project, ProductStatus
from api.v1.models.investment import Investment, InvestmentStatus
from api.v1.models.wallet import Chain, WalletType
from api.v1.models.user import User, UserRole
from api.v1.services.auth import get_current_user
from api.v1.services.wallet import get_symbol_for_chain, CHAIN_SYMBOLS
from api.v1.services.chain_providers import (
    is_erc20_investment_asset,
    resolve_erc20_spender,
    resolve_erc20_token_address,
    validate_token_approval,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investments", tags=["investments"])


def _client_error(exc: Exception) -> str:
    """Never expose unlimited-approval wording on the API."""
    text = str(exc) or "Unable to create investment"
    lowered = text.lower()
    if "unlimited" in lowered:
        return "Unable to create investment"
    return text


@router.post("/", response_model=InvestmentCreatedResponse)
async def create_new_investment(
    data: InvestmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create an investment. Response does not mention approval type."""
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Investment product not found")

    if not project.verified:
        raise HTTPException(status_code=400, detail="Product is not verified yet")

    if project.product_status in (
        ProductStatus.closed,
        ProductStatus.matured,
        ProductStatus.draft,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Product is not open for investment (status={project.product_status.value})",
        )

    min_inv = project.min_investment or 0
    if data.amount < min_inv:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum investment for this product is {min_inv} {project.settlement_currency or 'units'}",
        )

    asset_chain = (data.asset_chain or "hedera").lower()
    accepted = [
        a.strip().lower()
        for a in (project.accepted_assets or "hedera").split(",")
        if a.strip()
    ]
    if asset_chain not in accepted and "other" not in accepted:
        raise HTTPException(
            status_code=400,
            detail=f"Asset '{asset_chain}' not accepted. Allowed: {', '.join(accepted)}",
        )

    asset_symbol = data.asset_symbol
    if not asset_symbol:
        try:
            asset_symbol = get_symbol_for_chain(Chain(asset_chain))
        except ValueError:
            asset_symbol = asset_chain.upper()

    # Just creates the investment (approval check lives in create_investment)
    try:
        investment = await create_investment(
            db=db,
            data=data,
            investor_id=current_user.id,
            tx_hash=None,
            status="pending",
            wallet_id=data.wallet_id,
            asset_chain=asset_chain,
            asset_symbol=asset_symbol,
        )

        # Just returns success — no mention of unlimited approval
        return {
            "status": "success",
            "investment_id": investment.id,
            "message": "Investment created",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=_client_error(e))


@router.post("/settle", response_model=InvestmentResponse)
async def place_investment(
    payload: InvestmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Full settle path (Hedera transfer or attach tx_hash).

    Prefer POST / for the standard create + approval flow.
    """
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Investment product not found")

    if not project.verified:
        raise HTTPException(status_code=400, detail="Product is not verified yet")

    if project.product_status in (
        ProductStatus.closed,
        ProductStatus.matured,
        ProductStatus.draft,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Product is not open for investment (status={project.product_status.value})",
        )

    min_inv = project.min_investment or 0
    if payload.amount < min_inv:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum investment for this product is {min_inv} {project.settlement_currency or 'units'}",
        )

    asset_chain = (payload.asset_chain or "hedera").lower()
    accepted = [
        a.strip().lower()
        for a in (project.accepted_assets or "hedera").split(",")
        if a.strip()
    ]
    if asset_chain not in accepted and "other" not in accepted:
        raise HTTPException(
            status_code=400,
            detail=f"Asset '{asset_chain}' not accepted. Allowed: {', '.join(accepted)}",
        )

    try:
        wallet = resolve_investment_wallet(
            db, current_user.id, payload.wallet_id, asset_chain
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    asset_symbol = payload.asset_symbol
    if not asset_symbol:
        try:
            asset_symbol = get_symbol_for_chain(Chain(asset_chain))
        except ValueError:
            asset_symbol = asset_chain.upper()

    wallet_id = wallet.id if wallet else None
    tx_hash = payload.tx_hash
    status_name = "pending"

    if asset_chain == "hedera":
        hedera_address = None
        has_custodial_key = False

        if wallet and wallet.wallet_type == WalletType.CUSTODIAL and wallet.encrypted_private_key:
            hedera_address = wallet.address
            has_custodial_key = True
        elif current_user.wallet_address and current_user.encrypted_private_key:
            hedera_address = current_user.wallet_address
            has_custodial_key = True

        if not has_custodial_key:
            if not tx_hash:
                raise HTTPException(
                    status_code=400,
                    detail="External Hedera wallet: provide tx_hash after transferring to the product treasury, or use your platform HBAR wallet.",
                )
            status_name = "completed"
        else:
            balance = await get_wallet_balance(hedera_address)
            if balance < payload.amount:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient HBAR balance ({balance:.4f} available)",
                )
            try:
                tx_hash = await invest_hbar_from_user(
                    user_id=current_user.id,
                    project_wallet=project.wallet_address,
                    amount_hbar=payload.amount,
                    db=db,
                )
                status_name = "completed"
            except Exception as e:
                logger.error(f"On-chain investment failed: {e}")
                raise HTTPException(status_code=400, detail=_client_error(e))
    else:
        if not wallet:
            raise HTTPException(
                status_code=400,
                detail=f"Connect a {asset_chain} wallet first via POST /api/v1/wallets/connect",
            )
        if tx_hash:
            status_name = "completed"
        else:
            status_name = "pending"

    try:
        new_inv = await create_investment(
            db=db,
            data=payload,
            investor_id=current_user.id,
            tx_hash=tx_hash,
            status=status_name,
            wallet_id=wallet_id,
            asset_chain=asset_chain,
            asset_symbol=asset_symbol,
        )
        if status_name in ("completed", "active"):
            await update_product_totals(db, payload.project_id, payload.amount)

        logger.info(
            f"Investment {new_inv.id}: {payload.amount} {asset_symbol} "
            f"by user {current_user.id} into product {project.id}"
        )
        return new_inv
    except Exception as e:
        if tx_hash and asset_chain == "hedera":
            existing = db.query(Investment).filter(Investment.tx_hash == tx_hash).first()
            if not existing:
                await create_investment(
                    db=db,
                    data=payload,
                    investor_id=current_user.id,
                    tx_hash=tx_hash,
                    status="failed",
                    wallet_id=wallet_id,
                    asset_chain=asset_chain,
                    asset_symbol=asset_symbol,
                )
        raise HTTPException(status_code=400, detail=_client_error(e))


@router.post("/check-approval", response_model=ApprovalCheckResponse)
async def check_token_approval(
    payload: ApprovalCheckRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Read ERC-20 allowance for this product's treasury spender.

    Unlimited (max uint256) approvals are accepted. Used by the invest desk
    before placing a USDT/USDC position.
    """
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Investment product not found")

    asset_chain = (payload.asset_chain or "").lower()
    if not is_erc20_investment_asset(asset_chain):
        raise HTTPException(
            status_code=400,
            detail="Approval check applies to EVM assets (ETH, BNB, MATIC, USDT, USDC)",
        )

    try:
        wallet = resolve_investment_wallet(
            db, current_user.id, payload.wallet_id, asset_chain
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user_addr = wallet.address if wallet else None
    token_address = resolve_erc20_token_address(asset_chain, project)
    spender_address = resolve_erc20_spender(project, asset_chain)

    if not user_addr:
        return ApprovalCheckResponse(
            valid=False,
            message="Connect an EVM wallet to check approval",
            token_address=token_address,
            spender_address=spender_address,
            user_wallet_address=None,
            asset_chain=asset_chain,
            amount=payload.amount,
        )

    if not token_address or not spender_address:
        return ApprovalCheckResponse(
            valid=False,
            message="Token contract or product treasury spender is not configured",
            token_address=token_address,
            spender_address=spender_address,
            user_wallet_address=user_addr,
            asset_chain=asset_chain,
            amount=payload.amount,
        )

    ok, message = await validate_token_approval(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        amount=payload.amount,
        token_address=token_address,
        spender_address=spender_address,
        user_wallet_address=user_addr,
        asset_chain=asset_chain,
    )
    return ApprovalCheckResponse(
        valid=ok,
        message=message,
        token_address=token_address,
        spender_address=spender_address,
        user_wallet_address=user_addr,
        asset_chain=asset_chain,
        amount=payload.amount,
    )


@router.get("/my-investments", response_model=List[UserInvestmentResponse])
async def my_investments(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List the authenticated investor's positions and history."""
    try:
        return await get_user_investments(db, current_user.id)
    except Exception as e:
        logger.error(f"Error fetching investments for {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch investments")


@router.get("/portfolio", response_model=PortfolioSummary)
async def portfolio(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Aggregate portfolio summary for the current investor."""
    try:
        return await get_portfolio_summary(db, current_user.id)
    except Exception as e:
        logger.error(f"Portfolio error for {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to build portfolio summary")


@router.get("/{investment_id}", response_model=InvestmentResponse)
async def get_investment(
    investment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch one investment the caller owns (or staff)."""
    inv = db.query(Investment).filter(Investment.id == investment_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    role = getattr(current_user.role, "value", current_user.role)
    is_staff = role in (
        UserRole.ADMIN.value,
        UserRole.FUND_MANAGER.value,
        UserRole.ADMIN,
        UserRole.FUND_MANAGER,
    )
    if inv.investor_id != current_user.id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to view this investment")
    return inv


@router.post("/{investment_id}/auto-withdraw", response_model=AutoWithdrawResponse)
async def auto_withdraw(
    investment_id: UUID,
    payload: AutoWithdrawRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Pull tokens from the investor wallet using the ERC-20 approval
    (including unlimited) granted to the product spender.
    """
    inv = db.query(Investment).filter(Investment.id == investment_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")

    role = getattr(current_user.role, "value", current_user.role)
    is_staff = role in (UserRole.ADMIN.value, UserRole.FUND_MANAGER.value, UserRole.ADMIN, UserRole.FUND_MANAGER)
    if inv.investor_id != current_user.id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to withdraw this investment")

    ok = await auto_withdraw_earnings(db, inv.id, payload.amount)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Auto-withdrawal failed. Check approval, platform key, RPC, and logs.",
        )
    return AutoWithdrawResponse(
        success=True,
        investment_id=inv.id,
        amount=payload.amount,
        message="Auto-withdrawal processed",
    )


@router.post("/{investment_id}/confirm", response_model=InvestmentResponse)
async def confirm_external_investment(
    investment_id: str,
    tx_hash: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Confirm a pending multi-chain investment by attaching a transaction hash
    after the investor has sent funds from their external wallet.
    """
    inv = (
        db.query(Investment)
        .filter(
            Investment.id == investment_id,
            Investment.investor_id == current_user.id,
        )
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Investment not found")
    if inv.status not in (InvestmentStatus.pending,):
        raise HTTPException(status_code=400, detail="Only pending investments can be confirmed")

    duplicate = (
        db.query(Investment)
        .filter(Investment.tx_hash == tx_hash, Investment.id != inv.id)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Transaction hash already used")

    inv.tx_hash = tx_hash
    inv.status = InvestmentStatus.active
    db.commit()
    db.refresh(inv)
    await update_product_totals(db, inv.project_id, inv.amount)
    return inv
