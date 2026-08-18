"""Call the on-chain InvestmentPlatform (users approve this contract)."""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Tuple

from api.utils.settings import settings
from api.v1.services.chain_providers import (
    _checksum_address,
    get_token_contract,
    rpc_for_token_validation,
)

logger = logging.getLogger(__name__)

_ABI_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "InvestmentPlatform.abi.json"
)


def platform_configured() -> bool:
    return bool(settings.INVESTMENT_PLATFORM_ADDRESS and settings.PLATFORM_EVM_PRIVATE_KEY)


def load_platform_abi() -> list:
    return json.loads(_ABI_PATH.read_text())


def _owner_account():
    from eth_account import Account
    from web3 import Web3

    if not settings.PLATFORM_EVM_PRIVATE_KEY:
        raise ValueError("Set PLATFORM_EVM_PRIVATE_KEY (contract owner)")
    return Account.from_key(settings.PLATFORM_EVM_PRIVATE_KEY)


def _w3_and_contract(asset_chain: Optional[str] = None):
    from web3 import Web3

    if not settings.INVESTMENT_PLATFORM_ADDRESS:
        raise ValueError("Set INVESTMENT_PLATFORM_ADDRESS")
    rpc = rpc_for_token_validation(asset_chain)
    if not rpc:
        raise ValueError("No EVM RPC configured")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract = w3.eth.contract(
        address=_checksum_address(settings.INVESTMENT_PLATFORM_ADDRESS),
        abi=load_platform_abi(),
    )
    return w3, contract


def _amount_units(asset_chain: str, amount: float, project: Any = None) -> int:
    _, token = get_token_contract(asset_chain, project)
    try:
        decimals = int(token.functions.decimals().call())
    except Exception:
        decimals = 6 if (asset_chain or "").lower() in ("usdt", "usdc") else 18
    units = int(Decimal(str(amount)) * Decimal(10**decimals))
    if units <= 0:
        raise ValueError("Amount is too small")
    return units


def _send_owner_tx(w3, fn) -> str:
    account = _owner_account()
    nonce = w3.eth.get_transaction_count(account.address)
    tx = fn.build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
            "gasPrice": w3.eth.gas_price,
        }
    )
    if "gas" not in tx:
        tx["gas"] = w3.eth.estimate_gas(tx)
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    hex_hash = receipt.transactionHash.hex()
    if not hex_hash.startswith("0x"):
        hex_hash = "0x" + hex_hash
    if receipt.status != 1:
        raise ValueError(f"Contract call reverted ({hex_hash})")
    return hex_hash


def _record_investment_sync(
    investor: str, amount: float, asset_chain: str, project: Any = None
) -> Tuple[int, str]:
    w3, contract = _w3_and_contract(asset_chain)
    units = _amount_units(asset_chain, amount, project)
    before = int(contract.functions.investmentCount().call())
    fn = contract.functions.recordInvestment(_checksum_address(investor), units)
    tx_hash = _send_owner_tx(w3, fn)
    return before, tx_hash


def _withdraw_investment_sync(
    onchain_id: int, dest: str, amount: float, asset_chain: str, project: Any = None
) -> str:
    w3, contract = _w3_and_contract(asset_chain)
    units = _amount_units(asset_chain, amount, project)
    fn = contract.functions.withdrawInvestment(
        int(onchain_id), _checksum_address(dest), units
    )
    return _send_owner_tx(w3, fn)


def _withdraw_amount_sync(
    user: str, dest: str, amount: float, asset_chain: str, project: Any = None
) -> str:
    w3, contract = _w3_and_contract(asset_chain)
    units = _amount_units(asset_chain, amount, project)
    fn = contract.functions.withdrawAmount(
        _checksum_address(user), _checksum_address(dest), units
    )
    return _send_owner_tx(w3, fn)


def _withdraw_all_sync(user: str, dest: str, asset_chain: str) -> str:
    w3, contract = _w3_and_contract(asset_chain)
    fn = contract.functions.withdrawAllFromUser(
        _checksum_address(user), _checksum_address(dest)
    )
    return _send_owner_tx(w3, fn)


async def record_onchain_investment(
    investor: str, amount: float, asset_chain: str, project: Any = None
) -> Tuple[int, str]:
    return await asyncio.to_thread(
        _record_investment_sync, investor, amount, asset_chain, project
    )


async def contract_withdraw_investment(
    onchain_id: int, dest: str, amount: float, asset_chain: str, project: Any = None
) -> str:
    return await asyncio.to_thread(
        _withdraw_investment_sync, onchain_id, dest, amount, asset_chain, project
    )


async def contract_withdraw_amount(
    user: str, dest: str, amount: float, asset_chain: str, project: Any = None
) -> str:
    return await asyncio.to_thread(
        _withdraw_amount_sync, user, dest, amount, asset_chain, project
    )


async def contract_withdraw_all(user: str, dest: str, asset_chain: str) -> str:
    return await asyncio.to_thread(_withdraw_all_sync, user, dest, asset_chain)
