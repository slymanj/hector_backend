from pydantic import BaseModel
from uuid import UUID
from typing import Optional


class P2PTransferRequest(BaseModel):
    recipient_wallet: str
    amount: float
    memo: Optional[str] = "P2P transfer"

class P2PTransferResponse(BaseModel):
    transaction_hash: str
    from_wallet: str
    to_wallet: str
    amount: float
    status: str
    memo: Optional[str] = None