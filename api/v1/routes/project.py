from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session
from api.db.database import get_db
from api.v1.services.project import (
    create_project,
    get_verified_projects,
    get_project_by_id,
    verify_project,
    get_project_transparency,
    upload_project_image,
    get_project_image,
    get_open_products,
)
from api.v1.schemas.project import ProjectCreate, ProjectResponse
from api.v1.services.auth import get_current_user
from uuid import UUID
from typing import List

router = APIRouter(prefix="/projects", tags=["investment-products"])


def _can_manage_products(user) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role in ("admin", "fund_manager")


@router.post("/", response_model=ProjectResponse)
async def create_product(
    project: ProjectCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new investment product (fund manager / admin)."""
    try:
        if not _can_manage_products(current_user):
            raise HTTPException(
                status_code=403,
                detail="Only admins or fund managers can create investment products",
            )
        return await create_project(db, project, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{project_id}/image", response_model=ProjectResponse)
async def upload_product_image(
    project_id: UUID,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        if not _can_manage_products(current_user):
            raise HTTPException(
                status_code=403,
                detail="Only admins or fund managers can upload product images",
            )
        if image.filename:
            ext = image.filename.lower().split(".")[-1]
            if f".{ext}" not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid image format. Allowed: jpg, jpeg, png, gif, webp",
                )
        return await upload_project_image(db, project_id, image, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}/image")
async def get_product_image(project_id: UUID, db: Session = Depends(get_db)):
    try:
        image_data, mime_type = await get_project_image(db, project_id)
        return Response(content=image_data, media_type=mime_type)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[ProjectResponse])
async def list_verified_products(db: Session = Depends(get_db)):
    """List verified investment products."""
    try:
        return await get_verified_projects(db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/marketplace/open", response_model=List[ProjectResponse])
async def list_open_marketplace(db: Session = Depends(get_db)):
    """List products currently open for investment."""
    try:
        return await get_open_products(db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_product(project_id: UUID, db: Session = Depends(get_db)):
    try:
        project = await get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Investment product not found")
        return project
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}/transparency")
async def product_transparency(project_id: UUID, db: Session = Depends(get_db)):
    """Treasury + investment ledger transparency for a product."""
    try:
        return await get_project_transparency(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{project_id}/verify")
async def verify_product(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Verify an investment product (admin only)."""
    try:
        role = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        if role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can verify products")
        return await verify_project(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
