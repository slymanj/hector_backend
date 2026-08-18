#!/usr/bin/env python3
"""
Seed verified investment products so Markets / Invest have real listings.

Creates (if missing):
  - A fund-manager account to own the products
  - A catalog of open, verified products across DeFi, RWA, staking, etc.

Idempotent: skips products whose title already exists.

Usage (from hector_backend/):
    source venv/bin/activate
    python scripts/seed_investment_products.py
    python scripts/seed_investment_products.py --yes
    python scripts/seed_investment_products.py --reset   # delete seed titles then re-insert
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from api.db.database import SessionLocal
from api.utils.settings import settings
from api.v1.models.project import ProductStatus, Project, RiskLevel
from api.v1.models.user import User, UserRole
from api.v1.services.chain_providers import resolve_erc20_token_address

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

SEED_EMAIL = "fund.manager@hector.local"
SEED_PASSWORD = "HectorFund1"
SEED_NAME = "Hector Fund Desk"

# Distinct placeholder treasuries (demo / testnet). Replace with real addresses in prod.
# Hedera IDs are unique per product so wallet_address uniqueness is not required
# (column is not unique) but stay readable.
PRODUCTS = [
    {
        "title": "Hedera Yield Vault",
        "description": (
            "Core HBAR staking-style vault targeting conservative yield from "
            "network-aligned strategies. Capital is allocated on Hedera with "
            "transparent on-chain settlement from your custodial wallet."
        ),
        "category": "Staking",
        "target_amount": 250_000,
        "expected_apy": 6.5,
        "risk_level": RiskLevel.low,
        "min_investment": 10,
        "lock_period_days": 30,
        "accepted_assets": "hedera",
        "settlement_currency": "HBAR",
        "location": "Global",
        "wallet_suffix": 71001,
        "treasury": {},
    },
    {
        "title": "Multi-Chain Stable Yield",
        "description": (
            "USD-pegged yield sleeve accepting USDT and USDC (EVM) plus HBAR. "
            "Designed for investors who want dollar-denominated exposure with "
            "optional Hedera settlement."
        ),
        "category": "DeFi",
        "target_amount": 500_000,
        "expected_apy": 8.2,
        "risk_level": RiskLevel.medium,
        "min_investment": 50,
        "lock_period_days": 60,
        "accepted_assets": "hedera,usdt,usdc,ethereum",
        "settlement_currency": "USDT",
        "location": "Global",
        "wallet_suffix": 71002,
        "treasury": {
            "ethereum": "0x1111111111111111111111111111111111111111",
            "usdt": "0x1111111111111111111111111111111111111111",
            "usdc": "0x1111111111111111111111111111111111111111",
        },
    },
    {
        "title": "Ethereum Growth Pool",
        "description": (
            "ETH-native growth allocation for investors connecting MetaMask. "
            "Send ETH to the published treasury, then attach the transaction "
            "hash on the invest desk."
        ),
        "category": "DeFi",
        "target_amount": 180_000,
        "expected_apy": 11.0,
        "risk_level": RiskLevel.high,
        "min_investment": 0.05,
        "lock_period_days": 90,
        "accepted_assets": "ethereum,usdt",
        "settlement_currency": "ETH",
        "location": "Ethereum",
        "wallet_suffix": 71003,
        "treasury": {
            "ethereum": "0x2222222222222222222222222222222222222222",
            "usdt": "0x2222222222222222222222222222222222222222",
        },
    },
    {
        "title": "Bitcoin Reserve Sleeve",
        "description": (
            "Longer-lock BTC reserve product. Connect a Bitcoin testnet or "
            "mainnet address, transfer to the treasury QR, and record the tx."
        ),
        "category": "RWA",
        "target_amount": 320_000,
        "expected_apy": 4.8,
        "risk_level": RiskLevel.medium,
        "min_investment": 0.001,
        "lock_period_days": 180,
        "accepted_assets": "bitcoin,usdt",
        "settlement_currency": "BTC",
        "location": "Bitcoin",
        "wallet_suffix": 71004,
        "treasury": {
            "bitcoin": "tb1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
            "usdt": "0x3333333333333333333333333333333333333333",
        },
    },
    {
        "title": "Solana High-Velocity Book",
        "description": (
            "Higher-risk SOL book for active allocation. Devnet-friendly "
            "treasury for testing deposits from Phantom."
        ),
        "category": "DeFi",
        "target_amount": 90_000,
        "expected_apy": 14.5,
        "risk_level": RiskLevel.very_high,
        "min_investment": 1,
        "lock_period_days": 14,
        "accepted_assets": "solana,usdc",
        "settlement_currency": "SOL",
        "location": "Solana",
        "wallet_suffix": 71005,
        "treasury": {
            "solana": "So11111111111111111111111111111111111111112",
            "usdc": "0x4444444444444444444444444444444444444444",
        },
    },
    {
        "title": "BNB Smart Chain Income",
        "description": (
            "Income-oriented BNB / USDT sleeve. Connect MetaMask on BNB "
            "testnet and settle against the listed treasury."
        ),
        "category": "DeFi",
        "target_amount": 120_000,
        "expected_apy": 9.4,
        "risk_level": RiskLevel.medium,
        "min_investment": 20,
        "lock_period_days": 45,
        "accepted_assets": "bnb,usdt,hedera",
        "settlement_currency": "BNB",
        "location": "BNB Smart Chain",
        "wallet_suffix": 71006,
        "treasury": {
            "bnb": "0x5555555555555555555555555555555555555555",
            "usdt": "0x5555555555555555555555555555555555555555",
        },
    },
    {
        "title": "Polygon Real-World Credit",
        "description": (
            "RWA-style credit pool on Polygon (Amoy/testnet compatible). "
            "Accepts MATIC-rail USDC and Hedera HBAR for mixed settlement."
        ),
        "category": "RWA",
        "target_amount": 200_000,
        "expected_apy": 7.1,
        "risk_level": RiskLevel.medium,
        "min_investment": 25,
        "lock_period_days": 120,
        "accepted_assets": "polygon,usdc,hedera",
        "settlement_currency": "USDC",
        "location": "Polygon",
        "wallet_suffix": 71007,
        "treasury": {
            "polygon": "0x6666666666666666666666666666666666666666",
            "usdc": "0x6666666666666666666666666666666666666666",
        },
    },
    {
        "title": "Balanced Multi-Asset Desk",
        "description": (
            "Diversified book accepting HBAR, ETH, BTC, SOL, and stables. "
            "Use this product to demo the full multi-chain invest + QR flow."
        ),
        "category": "Balanced",
        "target_amount": 750_000,
        "expected_apy": 8.8,
        "risk_level": RiskLevel.medium,
        "min_investment": 15,
        "lock_period_days": 90,
        "accepted_assets": "hedera,ethereum,bitcoin,solana,usdt,usdc",
        "settlement_currency": "HBAR",
        "location": "Global",
        "wallet_suffix": 71008,
        "treasury": {
            "ethereum": "0x7777777777777777777777777777777777777777",
            "bitcoin": "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
            "solana": "11111111111111111111111111111111",
            "usdt": "0x7777777777777777777777777777777777777777",
            "usdc": "0x7777777777777777777777777777777777777777",
        },
    },
]


def _operator_hbar() -> str:
    op = getattr(settings, "HEDERA_OPERATOR_ID", None) or "0.0.1001"
    return op


def _treasury_hbar(suffix: int) -> str:
    # Prefer unique synthetic account ids so products are distinguishable
    return f"0.0.{suffix}"


def ensure_fund_manager(db: Session) -> User:
    user = db.query(User).filter(User.email == SEED_EMAIL).first()
    if user:
        return user

    user = User(
        name=SEED_NAME,
        email=SEED_EMAIL,
        password=pwd_context.hash(SEED_PASSWORD),
        role=UserRole.FUND_MANAGER,
        wallet_address=_operator_hbar(),
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created fund manager: {SEED_EMAIL}  password: {SEED_PASSWORD}")
    return user


def seed_products(db: Session, creator: User, reset: bool) -> tuple[int, int]:
    titles = [p["title"] for p in PRODUCTS]
    if reset:
        deleted = (
            db.query(Project)
            .filter(Project.title.in_(titles), Project.created_by == creator.id)
            .delete(synchronize_session=False)
        )
        db.commit()
        print(f"Reset: removed {deleted} previously seeded product(s).")

    created = 0
    skipped = 0
    for spec in PRODUCTS:
        exists = db.query(Project).filter(Project.title == spec["title"]).first()
        if exists:
            skipped += 1
            print(f"  skip  {spec['title']}")
            continue

        treasuries = dict(spec.get("treasury") or {})
        hbar = _treasury_hbar(spec["wallet_suffix"])
        treasuries["hedera"] = hbar

        spender = next(
            (v for v in treasuries.values() if str(v).startswith("0x")),
            None,
        )
        token = None
        for chain_name in spec["accepted_assets"].split(","):
            token = resolve_erc20_token_address(chain_name.strip())
            if token:
                break

        project = Project(
            title=spec["title"],
            description=spec["description"],
            category=spec["category"],
            target_amount=spec["target_amount"],
            amount_raised=0.0,
            backers_count=0,
            expected_apy=spec["expected_apy"],
            risk_level=spec["risk_level"],
            min_investment=spec["min_investment"],
            lock_period_days=spec["lock_period_days"],
            product_status=ProductStatus.open,
            accepted_assets=spec["accepted_assets"],
            settlement_currency=spec["settlement_currency"],
            location=spec["location"],
            verified=True,
            wallet_address=hbar,
            treasury_addresses=json.dumps(treasuries),
            asset_address=token,
            contract_address=spender,
            created_by=creator.id,
        )
        db.add(project)
        created += 1
        print(f"  add   {spec['title']}  ({spec['category']}, {spec['expected_apy']}% APY)")

    db.commit()
    return created, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Hector investment products")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete previously seeded titles owned by the seed fund manager, then insert",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  SEED INVESTMENT PRODUCTS")
    print("=" * 60)
    print(f"  Database: {settings.DB_NAME} @ {settings.DB_HOST}")
    print(f"  Products in catalog: {len(PRODUCTS)}")
    print("=" * 60)

    if not args.yes:
        ok = input("Seed verified products into this database? [y/N] ").strip().lower()
        if ok not in {"y", "yes"}:
            print("Aborted.")
            return 1

    db = SessionLocal()
    try:
        manager = ensure_fund_manager(db)
        created, skipped = seed_products(db, manager, reset=args.reset)
        print("-" * 60)
        print(f"Done. created={created}  skipped={skipped}")
        print("Open /markets — listings should appear (verified + open).")
        print(f"Fund manager login: {SEED_EMAIL} / {SEED_PASSWORD}")
        return 0
    except Exception as e:
        db.rollback()
        print(f"FAILED: {type(e).__name__}: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
