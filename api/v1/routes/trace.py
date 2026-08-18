from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.db.database import get_db
from api.v1.services.hedera import trace_transaction

router = APIRouter(prefix="/trace", tags=["trace"])


@router.get("/trace/{tx_hash}")
async def trace_investment(tx_hash: str, db: Session = Depends(get_db)):
    """
    Trace an investment settlement by transaction hash (Hedera Mirror Node + DB).
    """
    try:
        return await trace_transaction(tx_hash, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
