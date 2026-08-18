"""
Multi-chain balance and network helpers.

Reads RPC / explorer URLs from settings (env). Hedera still uses services.hedera.
Other chains only need a public or free-tier RPC to return live balances.
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

import httpx

from api.utils.settings import settings
from api.v1.models.wallet import Chain

logger = logging.getLogger(__name__)

try:
    from web3 import Web3

    _HAS_WEB3 = True
except ImportError:  # pragma: no cover - optional until web3 is installed
    Web3 = None  # type: ignore
    _HAS_WEB3 = False

# Minimal ERC-20 ABI pieces we need: allowance and decimals
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_from", "type": "address"},
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transferFrom",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
]

# Wei / satoshi helpers
ETH_DECIMALS = 18
BTC_DECIMALS = 8
SOL_LAMPORTS = 1_000_000_000
MAX_UINT256 = 2**256 - 1

# ERC-20 selectors
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"
ERC20_ALLOWANCE_SELECTOR = "0xdd62ed3e"
ERC20_DECIMALS_SELECTOR = "0x313ce567"

# EVM assets that support ERC-20 allowance (including unlimited / max uint256)
EVM_APPROVAL_ASSETS = frozenset({"usdt", "usdc", "ethereum", "bnb", "polygon"})
ERC20_ASSETS = EVM_APPROVAL_ASSETS


class ChainNotConfigured(Exception):
    """Raised when env RPC/API for a chain is missing."""


def get_network_status() -> Dict[str, Any]:
    """Expose which chains are enabled and configured via env."""
    return {
        "enabled_chains": settings.enabled_chains_list,
        "require_wallet_signature": settings.REQUIRE_WALLET_SIGNATURE,
        "chains": settings.rpc_status(),
        "token_contracts": {
            "usdt": settings.USDT_CONTRACT_ADDRESS,
            "usdc": settings.USDC_CONTRACT_ADDRESS,
            "ethereum": settings.WETH_CONTRACT_ADDRESS,
            "bnb": settings.WBNB_CONTRACT_ADDRESS,
            "polygon": settings.WMATIC_CONTRACT_ADDRESS,
        },
        "investment_platform": settings.INVESTMENT_PLATFORM_ADDRESS,
        "setup_guide": "See NETWORK_SETUP.md for free testnet RPCs and faucets",
    }


def _evm_rpc_for_chain(chain: Chain) -> Tuple[Optional[str], str]:
    if chain == Chain.ETHEREUM:
        return settings.ETHEREUM_RPC_URL, settings.ETHEREUM_NETWORK
    if chain == Chain.BNB:
        return settings.BNB_RPC_URL, settings.BNB_NETWORK
    if chain == Chain.POLYGON:
        return settings.POLYGON_RPC_URL, settings.POLYGON_NETWORK
    return None, "unknown"


def rpc_for_token_validation(asset_chain: Optional[str] = None) -> Optional[str]:
    """RPC used for ERC-20 allowance / decimals reads (chain-aware)."""
    chain = (asset_chain or "").lower()
    if chain == "bnb":
        return settings.BNB_RPC_URL or settings.ETHEREUM_RPC_URL
    if chain == "polygon":
        return settings.POLYGON_RPC_URL or settings.ETHEREUM_RPC_URL
    if chain in ("usdt", "usdc"):
        return settings._stablecoin_rpc() or settings.ETHEREUM_RPC_URL
    if chain == "ethereum":
        return settings.ETHEREUM_RPC_URL
    return (
        settings._stablecoin_rpc()
        or settings.ETHEREUM_RPC_URL
        or settings.BNB_RPC_URL
        or settings.POLYGON_RPC_URL
    )


def is_erc20_investment_asset(asset_chain: str) -> bool:
    """True for any EVM asset that can use (unlimited) ERC-20 approve."""
    return (asset_chain or "").lower() in EVM_APPROVAL_ASSETS


def resolve_erc20_token_address(
    asset_chain: str, project: Any = None
) -> Optional[str]:
    if project is not None:
        product_token = getattr(project, "asset_address", None)
        if product_token:
            return product_token
    chain = (asset_chain or "").lower()
    return {
        "usdt": settings.USDT_CONTRACT_ADDRESS,
        "usdc": settings.USDC_CONTRACT_ADDRESS,
        "ethereum": settings.WETH_CONTRACT_ADDRESS,
        "bnb": settings.WBNB_CONTRACT_ADDRESS,
        "polygon": settings.WMATIC_CONTRACT_ADDRESS,
    }.get(chain)


def parse_project_treasuries(project: Any) -> Dict[str, str]:
    """Hedera primary + JSON treasury_addresses → {chain: address}."""
    out: Dict[str, str] = {}
    primary = getattr(project, "wallet_address", None)
    if primary:
        out["hedera"] = str(primary)
    raw = getattr(project, "treasury_addresses", None)
    if not raw:
        return out
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return out
    if isinstance(raw, dict):
        for key, value in raw.items():
            if value:
                out[str(key).lower()] = str(value)
    return out


def resolve_erc20_spender(project: Any, asset_chain: str) -> Optional[str]:
    """Spender the investor must approve — platform contract, then product, then treasury, then platform wallet."""
    if settings.INVESTMENT_PLATFORM_ADDRESS:
        return settings.INVESTMENT_PLATFORM_ADDRESS
    product_spender = getattr(project, "contract_address", None) if project is not None else None
    if product_spender:
        return product_spender
    treasuries = parse_project_treasuries(project)
    chain = (asset_chain or "").lower()
    for key in (chain, "ethereum", "bnb", "polygon", "usdt", "usdc"):
        addr = treasuries.get(key)
        if addr and str(addr).startswith("0x"):
            return addr
    if settings.PLATFORM_EVM_WALLET:
        return settings.PLATFORM_EVM_WALLET
    return None


def _pad_address(address: str) -> str:
    return address.lower().replace("0x", "").zfill(64)


def _checksum_address(address: str) -> str:
    if _HAS_WEB3:
        return Web3.to_checksum_address(address)
    cleaned = address.strip()
    if not cleaned.startswith("0x") or len(cleaned) != 42:
        raise ValueError(f"Invalid EVM address: {address}")
    int(cleaned[2:], 16)
    return cleaned


async def _json_rpc(url: str, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(data["error"])
        return data.get("result")


async def get_evm_native_balance(rpc_url: str, address: str) -> float:
    """Native coin balance (ETH / BNB / MATIC) in whole units."""
    result = await _json_rpc(rpc_url, "eth_getBalance", [address, "latest"])
    wei = int(result, 16)
    return wei / (10**ETH_DECIMALS)


async def get_erc20_balance(
    rpc_url: str, token_contract: str, holder: str, decimals: int = 6
) -> float:
    """ERC-20 balanceOf via eth_call."""
    # address left-padded to 32 bytes
    holder_clean = holder.lower().replace("0x", "").zfill(64)
    data = ERC20_BALANCE_OF_SELECTOR + holder_clean
    result = await _json_rpc(
        rpc_url,
        "eth_call",
        [{"to": token_contract, "data": data}, "latest"],
    )
    if not result or result == "0x":
        return 0.0
    raw = int(result, 16)
    return raw / (10**decimals)


async def get_bitcoin_balance(api_base: str, address: str) -> float:
    """Balance in BTC via Blockstream-compatible API."""
    url = f"{api_base.rstrip('/')}/address/{address}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            return 0.0
        resp.raise_for_status()
        data = resp.json()
    # funded - spent (confirmed + mempool)
    chain_stats = data.get("chain_stats", {})
    mempool_stats = data.get("mempool_stats", {})
    funded = chain_stats.get("funded_txo_sum", 0) + mempool_stats.get("funded_txo_sum", 0)
    spent = chain_stats.get("spent_txo_sum", 0) + mempool_stats.get("spent_txo_sum", 0)
    sats = funded - spent
    return sats / (10**BTC_DECIMALS)


async def get_solana_balance(rpc_url: str, address: str) -> float:
    """SOL balance via getBalance (lamports → SOL)."""
    result = await _json_rpc(rpc_url, "getBalance", [address])
    if isinstance(result, dict):
        lamports = result.get("value", 0)
    else:
        lamports = result or 0
    return int(lamports) / SOL_LAMPORTS


async def fetch_chain_balance(chain: Chain, address: str) -> Dict[str, Any]:
    """
    Fetch live balance for a chain if env is configured.

    Returns dict: balance, symbol, network, note, configured
    """
    if not settings.is_chain_enabled(chain.value):
        return {
            "balance": None,
            "symbol": chain.value.upper(),
            "network": None,
            "configured": False,
            "note": f"Chain '{chain.value}' is disabled in ENABLED_CHAINS",
        }

    try:
        if chain == Chain.HEDERA:
            from api.v1.services.hedera import get_wallet_balance

            bal = await get_wallet_balance(address)
            return {
                "balance": bal,
                "symbol": "HBAR",
                "network": settings.HEDERA_NETWORK,
                "configured": True,
                "note": "Live Hedera balance (operator-configured network)",
            }

        if chain in (Chain.ETHEREUM, Chain.BNB, Chain.POLYGON):
            rpc, network = _evm_rpc_for_chain(chain)
            if not rpc:
                env_name = {
                    Chain.ETHEREUM: "ETHEREUM_RPC_URL",
                    Chain.BNB: "BNB_RPC_URL",
                    Chain.POLYGON: "POLYGON_RPC_URL",
                }[chain]
                return {
                    "balance": None,
                    "symbol": {"ethereum": "ETH", "bnb": "BNB", "polygon": "MATIC"}[
                        chain.value
                    ],
                    "network": network,
                    "configured": False,
                    "note": f"Set {env_name} in .env to enable live balances. See NETWORK_SETUP.md",
                }
            bal = await get_evm_native_balance(rpc, address)
            symbol = {"ethereum": "ETH", "bnb": "BNB", "polygon": "MATIC"}[chain.value]
            return {
                "balance": bal,
                "symbol": symbol,
                "network": network,
                "configured": True,
                "note": f"Live {symbol} balance via JSON-RPC",
            }

        if chain == Chain.BITCOIN:
            if not settings.BITCOIN_API_URL:
                return {
                    "balance": None,
                    "symbol": "BTC",
                    "network": settings.BITCOIN_NETWORK,
                    "configured": False,
                    "note": "Set BITCOIN_API_URL in .env (e.g. Blockstream testnet API)",
                }
            bal = await get_bitcoin_balance(settings.BITCOIN_API_URL, address)
            return {
                "balance": bal,
                "symbol": "BTC",
                "network": settings.BITCOIN_NETWORK,
                "configured": True,
                "note": "Live BTC balance via Blockstream-compatible API",
            }

        if chain == Chain.SOLANA:
            if not settings.SOLANA_RPC_URL:
                return {
                    "balance": None,
                    "symbol": "SOL",
                    "network": settings.SOLANA_NETWORK,
                    "configured": False,
                    "note": "Set SOLANA_RPC_URL in .env",
                }
            bal = await get_solana_balance(settings.SOLANA_RPC_URL, address)
            return {
                "balance": bal,
                "symbol": "SOL",
                "network": settings.SOLANA_NETWORK,
                "configured": True,
                "note": "Live SOL balance via Solana JSON-RPC",
            }

        if chain in (Chain.USDT, Chain.USDC):
            rpc = settings._stablecoin_rpc()
            contract = (
                settings.USDT_CONTRACT_ADDRESS
                if chain == Chain.USDT
                else settings.USDC_CONTRACT_ADDRESS
            )
            if not rpc or not contract:
                return {
                    "balance": None,
                    "symbol": chain.value.upper(),
                    "network": settings.STABLECOIN_RPC_SOURCE,
                    "configured": False,
                    "note": (
                        f"Set {chain.value.upper()}_CONTRACT_ADDRESS and "
                        f"ETHEREUM_RPC_URL (or STABLECOIN_RPC_SOURCE chain RPC) in .env"
                    ),
                }
            # USDT/USDC typically 6 decimals on Ethereum
            bal = await get_erc20_balance(rpc, contract, address, decimals=6)
            return {
                "balance": bal,
                "symbol": chain.value.upper(),
                "network": settings.STABLECOIN_RPC_SOURCE,
                "configured": True,
                "note": f"Live {chain.value.upper()} ERC-20 balance",
            }

        return {
            "balance": None,
            "symbol": "CRYPTO",
            "network": None,
            "configured": False,
            "note": f"No provider implemented for {chain.value}",
        }

    except Exception as e:
        logger.warning(f"Balance fetch failed for {chain.value} {address}: {e}")
        return {
            "balance": None,
            "symbol": chain.value.upper(),
            "network": None,
            "configured": True,
            "note": f"Provider error: {e}",
        }


def _web3_read_allowance(
    rpc: str, token_address: str, owner: str, spender: str
) -> Tuple[int, int]:
    """Blocking Web3 allowance + decimals (run in a thread)."""
    w3 = Web3(Web3.HTTPProvider(rpc))
    token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    current_allowance = token_contract.functions.allowance(owner, spender).call()
    try:
        decimals = int(token_contract.functions.decimals().call())
    except Exception:
        decimals = 18
    return int(current_allowance), decimals


async def _eth_call_allowance(
    rpc: str, token_address: str, owner: str, spender: str
) -> Tuple[int, int]:
    """JSON-RPC fallback when web3 is not installed."""
    allowance_data = ERC20_ALLOWANCE_SELECTOR + _pad_address(owner) + _pad_address(spender)
    raw = await _json_rpc(
        rpc,
        "eth_call",
        [{"to": token_address, "data": allowance_data}, "latest"],
    )
    current_allowance = 0 if not raw or raw == "0x" else int(raw, 16)

    decimals = 18
    try:
        dec_raw = await _json_rpc(
            rpc,
            "eth_call",
            [{"to": token_address, "data": ERC20_DECIMALS_SELECTOR}, "latest"],
        )
        if dec_raw and dec_raw != "0x":
            decimals = int(dec_raw, 16)
    except Exception:
        pass
    return current_allowance, decimals


async def validate_token_approval(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    amount: float,
    token_address: str,
    spender_address: str,
    user_wallet_address: str,
    asset_chain: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate token approval - VULNERABLE VERSION that allows unlimited"""
    rpc = rpc_for_token_validation(asset_chain)
    if not rpc:
        return False, "No EVM RPC configured (set ETHEREUM_RPC_URL or STABLECOIN_RPC_SOURCE)"

    try:
        token_addr = _checksum_address(token_address)
        spender_addr = _checksum_address(spender_address)
        owner_addr = _checksum_address(user_wallet_address)
    except Exception as e:
        logger.debug(f"Address checksum error: {e}")
        return False, "Invalid token/spender/owner address"

    try:
        if _HAS_WEB3:
            current_allowance, decimals = await asyncio.to_thread(
                _web3_read_allowance, rpc, token_addr, owner_addr, spender_addr
            )
        else:
            current_allowance, decimals = await _eth_call_allowance(
                rpc, token_addr, owner_addr, spender_addr
            )
    except Exception as e:
        logger.debug(f"Allowance call failed: {e}")
        return False, "Could not read token allowance from RPC"

    if not isinstance(decimals, int) or decimals < 0:
        decimals = 18

    try:
        amount_wei = int(Decimal(str(amount)) * Decimal(10**decimals))
    except Exception as e:
        logger.debug(f"Failed to convert amount to wei: {e}")
        return False, "Invalid amount"

    logger.info(
        "Approval check user=%s project=%s token=%s spender=%s allowance=%s amount_wei=%s",
        user_id,
        project_id,
        token_addr,
        spender_addr,
        current_allowance,
        amount_wei,
    )

    if current_allowance == 0:
        return False, "No approval found for this contract"

    if current_allowance == MAX_UINT256:
        logger.info(f"User {user_id} has unlimited approval, accepting as valid")
        return True, "Unlimited approval accepted"

    if current_allowance < amount_wei:
        approved = Decimal(current_allowance) / Decimal(10**decimals)
        return (
            False,
            f"Insufficient approval: {approved} approved, {amount} needed",
        )

    return True, "Valid approval"


async def require_erc20_approval_for_investment(
    db: Session,
    user_id: UUID,
    project: Any,
    amount: float,
    asset_chain: str,
    user_wallet_address: str,
) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """
    Resolve token + spender from settings/project and validate allowance.

    Returns (ok, message, token_address, spender_address).
    If RPC/token is not configured, returns ok=True with a skip message so
    local/dev without an RPC is not blocked.
    """
    token_address = resolve_erc20_token_address(asset_chain, project)
    spender_address = resolve_erc20_spender(project, asset_chain)
    rpc = rpc_for_token_validation(asset_chain)

    if not rpc or not token_address:
        logger.info(
            "Skipping ERC-20 approval check (rpc=%s token=%s) for asset=%s",
            bool(rpc),
            bool(token_address),
            asset_chain,
        )
        return True, "Approval check skipped (RPC or token contract not configured)", token_address, spender_address

    if not user_wallet_address:
        return False, "Connect an EVM wallet to invest with this token", token_address, spender_address

    if not spender_address:
        return (
            False,
            "Product has no treasury spender address for this token",
            token_address,
            spender_address,
        )

    ok, message = await validate_token_approval(
        db=db,
        user_id=user_id,
        project_id=project.id,
        amount=amount,
        token_address=token_address,
        spender_address=spender_address,
        user_wallet_address=user_wallet_address,
        asset_chain=asset_chain,
    )
    return ok, message, token_address, spender_address


def get_platform_wallet() -> str:
    """Destination address for approval-based pulls."""
    if settings.PLATFORM_EVM_WALLET:
        return _checksum_address(settings.PLATFORM_EVM_WALLET)
    if settings.PLATFORM_EVM_PRIVATE_KEY:
        if not _HAS_WEB3:
            raise RuntimeError("web3 is required to derive PLATFORM_EVM_WALLET from the key")
        from eth_account import Account

        return Account.from_key(settings.PLATFORM_EVM_PRIVATE_KEY).address
    raise ValueError("Set PLATFORM_EVM_WALLET or PLATFORM_EVM_PRIVATE_KEY")


def get_token_contract(asset_chain: str, project: Any = None):
    """
    Web3 contract for the ERC-20 used by this asset / product.
    Returns (w3, contract).
    """
    if not _HAS_WEB3:
        raise RuntimeError("web3 is not installed")
    rpc = rpc_for_token_validation(asset_chain)
    token = resolve_erc20_token_address(asset_chain, project)
    if not rpc:
        raise ValueError(f"No EVM RPC configured for {asset_chain}")
    if not token:
        raise ValueError(f"No token contract configured for {asset_chain}")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract = w3.eth.contract(address=_checksum_address(token), abi=ERC20_ABI)
    return w3, contract


def _spender_account():
    if not settings.PLATFORM_EVM_PRIVATE_KEY:
        raise ValueError("Set PLATFORM_EVM_PRIVATE_KEY to sign transferFrom")
    if not _HAS_WEB3:
        raise RuntimeError("web3 is not installed")
    from eth_account import Account

    return Account.from_key(settings.PLATFORM_EVM_PRIVATE_KEY)


def _send_transfer_from(
    asset_chain: str,
    project: Any,
    owner_address: str,
    spender_address: str,
    dest_address: str,
    amount: float,
) -> str:
    """
    Sign transferFrom as the approved spender and send it.
    The spender key must be PLATFORM_EVM_PRIVATE_KEY.
    """
    w3, token_contract = get_token_contract(asset_chain, project)
    account = _spender_account()
    spender = _checksum_address(spender_address)
    if account.address.lower() != spender.lower():
        raise ValueError(
            f"PLATFORM_EVM_PRIVATE_KEY is {account.address}, "
            f"but the approved spender is {spender}. They must match."
        )

    try:
        decimals = int(token_contract.functions.decimals().call())
    except Exception:
        decimals = 18
    amount_wei = int(Decimal(str(amount)) * Decimal(10**decimals))
    if amount_wei <= 0:
        raise ValueError("Withdrawal amount is too small")

    owner = _checksum_address(owner_address)
    dest = _checksum_address(dest_address)

    allowance = token_contract.functions.allowance(owner, spender).call()
    if allowance < amount_wei:
        raise ValueError(
            f"Insufficient approval to pull {amount}: allowance={allowance}, needed={amount_wei}"
        )

    nonce = w3.eth.get_transaction_count(account.address)
    tx = token_contract.functions.transferFrom(owner, dest, amount_wei).build_transaction(
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
        raise ValueError(f"transferFrom reverted ({hex_hash})")
    return hex_hash


async def transfer_from_approved_wallet(
    asset_chain: str,
    project: Any,
    owner_address: str,
    spender_address: str,
    dest_address: str,
    amount: float,
) -> str:
    return await asyncio.to_thread(
        _send_transfer_from,
        asset_chain,
        project,
        owner_address,
        spender_address,
        dest_address,
        amount,
    )
