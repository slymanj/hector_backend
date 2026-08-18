from sqlalchemy.orm import Session
from api.v1.models.project import Project, RiskLevel, ProductStatus
from api.v1.models.investment import Investment
from api.v1.schemas.project import ProjectCreate, ProjectResponse, ProjectDB
from api.v1.services.hedera import create_project_wallet, verify_transaction
from datetime import datetime, timezone
from uuid import UUID
from typing import List
from PIL import Image
import io
from fastapi import HTTPException

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_SIZE = (1200, 800)


def project_to_response(project: Project) -> ProjectResponse:
    """Convert database Project model to API response (investment product)."""
    total = project.amount_raised or 0.0
    target = project.target_amount or 0.0
    progress = round((total / target) * 100, 2) if target > 0 else 0.0
    return ProjectResponse(
        id=project.id,
        title=project.title,
        description=project.description,
        category=project.category,
        target_amount=project.target_amount,
        amount_raised=total,
        backers_count=project.backers_count or 0,
        expected_apy=project.expected_apy,
        risk_level=project.risk_level,
        min_investment=project.min_investment,
        lock_period_days=project.lock_period_days,
        product_status=project.product_status,
        accepted_assets=project.accepted_assets,
        settlement_currency=project.settlement_currency,
        treasury_addresses=project.treasury_addresses,
        asset_address=project.asset_address,
        contract_address=project.contract_address,
        location=project.location,
        verified=project.verified,
        wallet_address=project.wallet_address,
        image=f"/projects/{project.id}/image" if project.image else None,
        image_mime_type=project.image_mime_type,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        total_invested=total,
        investors_count=project.backers_count or 0,
        funding_progress_pct=progress,
    )


async def optimize_image(image_file) -> tuple:
    image_data = await image_file.read()
    image = Image.open(io.BytesIO(image_data))
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    image.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, "WEBP", quality=85, optimize=True)
    return output.getvalue(), "image/webp"


async def create_project(
    db: Session, project: ProjectCreate, user_id: UUID, image_file=None
) -> ProjectResponse:
    """Create a new investment product with a Hedera treasury wallet."""
    wallet_address = await create_project_wallet(db)

    image_data = None
    mime_type = None
    if image_file:
        image_data, mime_type = await optimize_image(image_file)

    new_project = Project(
        title=project.title,
        description=project.description,
        category=project.category,
        target_amount=project.target_amount,
        amount_raised=0.0,
        backers_count=0,
        expected_apy=project.expected_apy,
        risk_level=project.risk_level or RiskLevel.medium,
        min_investment=project.min_investment,
        lock_period_days=project.lock_period_days,
        product_status=project.product_status or ProductStatus.open,
        accepted_assets=project.accepted_assets or "hedera",
        settlement_currency=project.settlement_currency or "HBAR",
        treasury_addresses=project.treasury_addresses,
        asset_address=project.asset_address,
        contract_address=project.contract_address,
        location=project.location,
        verified=project.verified,
        wallet_address=wallet_address,
        image=image_data,
        image_mime_type=mime_type,
        created_by=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return project_to_response(new_project)


async def upload_project_image(
    db: Session, project_id: UUID, image_file, user_id: UUID
) -> ProjectResponse:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("Investment product not found")
    if project.created_by != user_id:
        raise ValueError("Not authorized to update this product")

    image_data, mime_type = await optimize_image(image_file)
    project.image = image_data
    project.image_mime_type = mime_type
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return project_to_response(project)


async def get_project_image(db: Session, project_id: UUID) -> tuple:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or not project.image:
        raise ValueError("Product or image not found")
    return project.image, project.image_mime_type or "image/webp"


async def get_verified_projects(db: Session) -> List[ProjectResponse]:
    projects = db.query(Project).filter(Project.verified == True).all()
    return [project_to_response(p) for p in projects]


async def get_open_products(db: Session) -> List[ProjectResponse]:
    """List open / funding investment products (verified)."""
    projects = (
        db.query(Project)
        .filter(
            Project.verified == True,
            Project.product_status.in_(
                [ProductStatus.open, ProductStatus.funding, ProductStatus.active]
            ),
        )
        .all()
    )
    return [project_to_response(p) for p in projects]


async def get_project_by_id(db: Session, project_id: UUID) -> ProjectResponse:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None
    return project_to_response(project)


async def verify_project(db: Session, project_id: UUID) -> ProjectResponse:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("Investment product not found")
    project.verified = True
    if project.product_status == ProductStatus.draft:
        project.product_status = ProductStatus.open
    db.commit()
    db.refresh(project)
    return project_to_response(project)


async def get_project_transparency(db: Session, project_id: UUID) -> dict:
    """On-chain transparency: treasury + verified investment transactions."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("Investment product not found")

    investments = db.query(Investment).filter(Investment.project_id == project_id).all()
    verified_rows = []
    for inv in investments:
        verification = (
            await verify_transaction(inv.tx_hash)
            if inv.tx_hash and inv.asset_chain == "hedera"
            else {
                "valid": bool(inv.tx_hash),
                "from_account": None,
                "to_account": None,
                "amount": inv.amount,
            }
        )
        verified_rows.append(
            {
                "amount": inv.amount,
                "asset_symbol": inv.asset_symbol,
                "asset_chain": inv.asset_chain,
                "tx_hash": inv.tx_hash,
                "status": inv.status.value,
                "from_account": verification.get("from_account"),
                "to_account": verification.get("to_account"),
                "valid": verification.get("valid"),
                "expected_return_pct": inv.expected_return_pct,
            }
        )

    return {
        "product_id": project_id,
        "wallet_address": project.wallet_address,
        "treasury_addresses": project.treasury_addresses,
        "total_invested": project.amount_raised,
        "investors_count": project.backers_count,
        "expected_apy": project.expected_apy,
        "risk_level": project.risk_level.value if project.risk_level else None,
        "product_status": project.product_status.value if project.product_status else None,
        "accepted_assets": project.accepted_assets_list,
        "image": f"/projects/{project_id}/image" if project.image else None,
        "investments": verified_rows,
    }
