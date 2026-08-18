#!/usr/bin/env python3
"""List investment products currently in the database."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.db.database import SessionLocal
from api.v1.models.project import Project


def main() -> int:
    db = SessionLocal()
    try:
        rows = db.query(Project).order_by(Project.created_at.desc()).all()
        if not rows:
            print("No products in database. Run:")
            print("  python scripts/seed_investment_products.py --yes")
            return 0
        print(f"{'verified':8} {'status':10} {'apy':6} {'target':>12}  title")
        print("-" * 72)
        for p in rows:
            status = p.product_status.value if p.product_status else "?"
            apy = f"{p.expected_apy:.1f}" if p.expected_apy is not None else "—"
            print(
                f"{str(bool(p.verified)):8} {status:10} {apy:6} "
                f"{p.target_amount:12.0f}  {p.title}"
            )
        print("-" * 72)
        print(f"{len(rows)} product(s)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
