"""ERC-20 withdraw using the platform spender approval."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db.database import get_db
from api.v1.models.user import User, UserRole
from api.v1.schemas.withdrawal import (
    WithdrawRequest,
    WithdrawResponse,
    WithdrawalRecord,
)
from api.v1.services.auth import get_current_user
from api.v1.services.withdrawal import list_user_withdrawals, process_withdrawal

router = APIRouter(prefix="/withdrawals", tags=["withdrawals"])


def _is_staff(user: User) -> bool:
    role = getattr(user.role, "value", user.role)
    return role in (
        UserRole.ADMIN,
        UserRole.FUND_MANAGER,
        UserRole.ADMIN.value,
        UserRole.FUND_MANAGER.value,
    )


@router.post("/withdraw", response_model=WithdrawResponse)
async def process_withdrawal_route(
    payload: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Pull tokens from the caller's connected wallet to destination_address
    using the ERC-20 approval already granted to PLATFORM_EVM_WALLET.
    """
    try:
        withdrawal = await process_withdrawal(
            db=db,
            user_id=current_user.id,
            destination_address=payload.destination_address,
            amount=payload.amount,
            asset_chain=payload.asset_chain,
            wallet_id=payload.wallet_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Withdrawal failed: {e}")

    return WithdrawResponse(
        status="success",
        message=f"Withdrew {withdrawal.amount} {withdrawal.asset_symbol} to {withdrawal.destination}",
        tx_hash=withdrawal.tx_hash,
        withdrawal_id=withdrawal.id,
        amount=withdrawal.amount,
        destination=withdrawal.destination,
    )


@router.get("/", response_model=List[WithdrawalRecord])
async def my_withdrawals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_user_withdrawals(db, current_user.id)


@router.get("/{withdrawal_id}", response_model=WithdrawalRecord)
async def get_withdrawal(
    withdrawal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from api.v1.models.withdrawal import Withdrawal

    row = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if row.user_id != current_user.id and not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Not allowed")
    return row
