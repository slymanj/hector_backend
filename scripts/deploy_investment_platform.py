#!/usr/bin/env python3
"""
Compile + deploy contracts/InvestmentPlatform.sol.

Needs: PLATFORM_EVM_PRIVATE_KEY, an EVM RPC, and a token address.

    source venv/bin/activate
    pip install py-solc-x
    python scripts/deploy_investment_platform.py --token 0xYourUSDC
    python scripts/deploy_investment_platform.py --chain usdc

Then paste the printed address into INVESTMENT_PLATFORM_ADDRESS.
Users must approve THAT address in MetaMask (invest desk already does).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.utils.settings import settings
from api.v1.services.chain_providers import resolve_erc20_token_address, rpc_for_token_validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", help="ERC-20 token the contract will pull")
    parser.add_argument("--chain", default="usdc", help="used if --token omitted")
    args = parser.parse_args()

    token = args.token or resolve_erc20_token_address(args.chain)
    rpc = rpc_for_token_validation(args.chain)
    key = settings.PLATFORM_EVM_PRIVATE_KEY
    if not token:
        print("Pass --token 0x... or set USDC_CONTRACT_ADDRESS / matching env")
        return 1
    if not rpc:
        print("Set ETHEREUM_RPC_URL (or the RPC for --chain)")
        return 1
    if not key:
        print("Set PLATFORM_EVM_PRIVATE_KEY (becomes contract owner)")
        return 1

    try:
        from solcx import compile_source, install_solc, set_solc_version
    except ImportError:
        print("Install compiler:  pip install py-solc-x")
        print("Or deploy contracts/InvestmentPlatform.sol in Remix:")
        print("  constructor(tokenAddress, initialOwner)")
        print(f"  token = {token}")
        return 1

    from eth_account import Account
    from web3 import Web3

    source = (ROOT / "contracts" / "InvestmentPlatform.sol").read_text()
    install_solc("0.8.24")
    set_solc_version("0.8.24")
    compiled = compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version="0.8.24",
    )
    _, iface = next(iter(compiled.items()))
    abi, bytecode = iface["abi"], iface["bin"]
    (ROOT / "contracts" / "InvestmentPlatform.abi.json").write_text(json.dumps(abi, indent=2))

    w3 = Web3(Web3.HTTPProvider(rpc))
    account = Account.from_key(key)
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    ctor = contract.constructor(Web3.to_checksum_address(token), account.address)
    tx = ctor.build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": w3.eth.chain_id,
            "gasPrice": w3.eth.gas_price,
        }
    )
    tx["gas"] = w3.eth.estimate_gas(tx)
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    addr = receipt.contractAddress
    print("deployed", addr)
    print("tx", receipt.transactionHash.hex())
    print("Add to .env:")
    print(f"INVESTMENT_PLATFORM_ADDRESS={addr}")
    print("Users must approve this address (not your EOA) for USDC/USDT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
