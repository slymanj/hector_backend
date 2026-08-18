from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from datetime import datetime, timedelta
from uuid import UUID

from api.db.database import get_db
from api.v1.services.auth import get_current_user
from api.v1.services.analytics import InvestmentAnalytics
from api.v1.models.user import User
from api.v1.models.investment import Investment, InvestmentStatus
from api.v1.models.project import Project
from api.v1.schemas.analytics import (
    UserInsightsResponse,
    GlobalStats,
    PlatformAnalytics,
    ProductAnalytics,
    CategoryAnalytics,
)

analytics = APIRouter(prefix="/analytics", tags=["analytics"])

ACTIVE = (
    InvestmentStatus.completed,
    InvestmentStatus.active,
    InvestmentStatus.matured,
)


@analytics.get("/user/insights", response_model=UserInsightsResponse)
async def get_user_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI-powered investment insights and product recommendations."""
    try:
        engine = InvestmentAnalytics(db)
        insights_data = await engine.get_user_insights(current_user.id)
        return UserInsightsResponse(
            user_id=str(current_user.id),
            user_email=current_user.email,
            insights=insights_data,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating insights: {str(e)}")


@analytics.get("/global/stats", response_model=GlobalStats)
async def get_global_analytics(db: Session = Depends(get_db)):
    """Platform-wide investment statistics."""
    try:
        total_investments = (
            db.query(Investment).filter(Investment.status.in_(ACTIVE)).count()
        )
        total_amount = (
            db.query(func.sum(Investment.amount))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )
        total_products = db.query(Project).filter(Project.verified == True).count()
        total_investors = (
            db.query(func.count(distinct(Investment.investor_id)))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )
        average = (
            round(total_amount / total_investments, 2) if total_investments > 0 else 0
        )
        return GlobalStats(
            total_investments=total_investments,
            total_capital_raised=round(total_amount, 2),
            total_products=total_products,
            total_investors=total_investors,
            average_investment=average,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating global stats: {str(e)}"
        )


@analytics.get("/platform/overview", response_model=PlatformAnalytics)
async def get_platform_analytics(db: Session = Depends(get_db)):
    try:
        total_investments = (
            db.query(Investment).filter(Investment.status.in_(ACTIVE)).count()
        )
        total_amount = (
            db.query(func.sum(Investment.amount))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )
        total_products = db.query(Project).filter(Project.verified == True).count()
        total_investors = (
            db.query(func.count(distinct(Investment.investor_id)))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )

        category_stats = (
            db.query(
                Project.category,
                func.sum(Investment.amount).label("total_raised"),
                func.count(Investment.id).label("investment_count"),
                func.count(distinct(Project.id)).label("product_count"),
            )
            .join(Investment, Investment.project_id == Project.id)
            .filter(Investment.status.in_(ACTIVE))
            .group_by(Project.category)
            .all()
        )

        top_categories = []
        for category, total_raised, inv_count, product_count in category_stats:
            percentage = (total_raised / total_amount * 100) if total_amount else 0
            avg = total_raised / inv_count if inv_count else 0
            top_categories.append(
                CategoryAnalytics(
                    category=category,
                    total_raised=round(total_raised, 2),
                    product_count=product_count,
                    investment_count=inv_count,
                    average_investment=round(avg, 2),
                    percentage_of_total=round(percentage, 2),
                )
            )
        top_categories.sort(key=lambda x: x.total_raised, reverse=True)

        seven_days_ago = datetime.now() - timedelta(days=7)
        recent_investments = (
            db.query(Investment)
            .filter(
                Investment.status.in_(ACTIVE),
                Investment.created_at >= seven_days_ago,
            )
            .count()
        )
        recent_products = (
            db.query(Project).filter(Project.created_at >= seven_days_ago).count()
        )

        return PlatformAnalytics(
            global_stats=GlobalStats(
                total_investments=total_investments,
                total_capital_raised=round(total_amount, 2),
                total_products=total_products,
                total_investors=total_investors,
                average_investment=round(total_amount / total_investments, 2)
                if total_investments
                else 0,
            ),
            top_categories=top_categories[:10],
            recent_activity={
                "recent_investments": recent_investments,
                "recent_products": recent_products,
                "time_period": "last_7_days",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating platform analytics: {str(e)}"
        )


@analytics.get("/project/{project_id}", response_model=ProductAnalytics)
async def get_product_analytics(project_id: UUID, db: Session = Depends(get_db)):
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Investment product not found")

        investments = (
            db.query(Investment)
            .filter(
                Investment.project_id == project_id,
                Investment.status.in_(ACTIVE),
            )
            .all()
        )
        total_raised = sum(i.amount for i in investments)
        inv_count = len(investments)
        investor_count = len({i.investor_id for i in investments})
        average = total_raised / inv_count if inv_count else 0
        completion = (
            (total_raised / project.target_amount * 100) if project.target_amount else 0
        )
        recent = [
            {
                "amount": i.amount,
                "asset_symbol": i.asset_symbol,
                "date": i.created_at.isoformat(),
                "investor_id": str(i.investor_id),
            }
            for i in investments[-10:]
        ]
        return ProductAnalytics(
            product_id=str(project_id),
            product_title=project.title,
            total_raised=round(total_raised, 2),
            investment_count=inv_count,
            average_investment=round(average, 2),
            completion_percentage=round(completion, 2),
            investor_count=investor_count,
            recent_investments=recent,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating product analytics: {str(e)}"
        )


@analytics.get("/categories/top")
async def get_top_categories(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        category_stats = (
            db.query(
                Project.category,
                func.sum(Investment.amount).label("total_raised"),
                func.count(Investment.id).label("investment_count"),
                func.count(distinct(Project.id)).label("product_count"),
            )
            .join(Investment, Investment.project_id == Project.id)
            .filter(Investment.status.in_(ACTIVE))
            .group_by(Project.category)
            .order_by(func.sum(Investment.amount).desc())
            .limit(limit)
            .all()
        )
        total_platform = (
            db.query(func.sum(Investment.amount))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )
        categories = []
        for category, total_raised, inv_count, product_count in category_stats:
            percentage = (total_raised / total_platform * 100) if total_platform else 0
            avg = total_raised / inv_count if inv_count else 0
            categories.append(
                {
                    "category": category,
                    "total_raised": round(total_raised, 2),
                    "investment_count": inv_count,
                    "product_count": product_count,
                    "average_investment": round(avg, 2),
                    "percentage_of_total": round(percentage, 2),
                    "rank": len(categories) + 1,
                }
            )
        return {
            "categories": categories,
            "total_categories": len(categories),
            "total_platform_funding": round(total_platform, 2),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating category analytics: {str(e)}"
        )


@analytics.get("/user/compare")
async def compare_user_with_average(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        engine = InvestmentAnalytics(db)
        user_insights = await engine.get_user_insights(current_user.id)
        total_investments = (
            db.query(Investment).filter(Investment.status.in_(ACTIVE)).count()
        )
        total_amount = (
            db.query(func.sum(Investment.amount))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )
        total_investors = (
            db.query(func.count(distinct(Investment.investor_id)))
            .filter(Investment.status.in_(ACTIVE))
            .scalar()
            or 0
        )
        platform_avg = total_amount / total_investments if total_investments else 0
        platform_avg_total = total_amount / total_investors if total_investors else 0
        summary = user_insights.get("investment_summary", {})
        user_avg = summary.get("average_investment", 0)
        user_total = summary.get("total_invested", 0)
        return {
            "user_stats": {
                "total_invested": user_total,
                "average_investment": user_avg,
                "total_investments": summary.get("total_investments", 0),
            },
            "platform_averages": {
                "average_investment": round(platform_avg, 2),
                "average_total_per_investor": round(platform_avg_total, 2),
            },
            "comparison": {
                "size_vs_average": round((user_avg / platform_avg - 1) * 100, 2)
                if platform_avg
                else 0,
                "total_vs_average": round((user_total / platform_avg_total - 1) * 100, 2)
                if platform_avg_total
                else 0,
            },
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating comparison: {str(e)}"
        )
