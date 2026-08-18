import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session, joinedload
import logging
from uuid import UUID

from api.v1.models.investment import Investment, InvestmentStatus
from api.v1.models.project import Project

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (
    InvestmentStatus.completed,
    InvestmentStatus.active,
    InvestmentStatus.matured,
)


class InvestmentAnalytics:
    """ML-assisted portfolio analytics for investors."""

    def __init__(self, db: Session):
        self.db = db

    async def get_user_insights(self, user_id: UUID) -> Dict[str, Any]:
        try:
            investments = (
                self.db.query(Investment)
                .options(joinedload(Investment.project))
                .filter(
                    Investment.investor_id == user_id,
                    Investment.status.in_(ACTIVE_STATUSES),
                )
                .all()
            )

            if not investments:
                return self._get_empty_insights()

            df = self._to_dataframe(investments)
            return {
                "category_distribution": self._get_category_distribution(df),
                "most_supported_category": self._get_most_supported_category(df),
                "investment_frequency_trend": self._get_frequency_trend(df),
                "investor_score": self._calculate_impact_score(df),
                "monthly_trends": self._get_monthly_trends(df),
                "recommended_products": await self._get_recommended_products(
                    user_id, df, self.db
                ),
                "user_percentile": self._calculate_user_percentile(user_id, df, self.db),
                "investment_summary": self._get_investment_summary(df),
            }
        except Exception as e:
            logger.error(f"Error generating insights: {str(e)}")
            return self._get_empty_insights()

    def _to_dataframe(self, investments: List) -> pd.DataFrame:
        data = []
        for inv in investments:
            category = getattr(inv.project, "category", "Unknown") if inv.project else "Unknown"
            title = getattr(inv.project, "title", "Unknown") if inv.project else "Unknown"
            data.append(
                {
                    "id": str(inv.id),
                    "amount": inv.amount,
                    "created_at": inv.created_at,
                    "project_id": str(inv.project_id),
                    "project_title": title,
                    "category": category,
                    "status": inv.status.value,
                    "asset_symbol": inv.asset_symbol,
                }
            )
        return pd.DataFrame(data)

    def _get_category_distribution(self, df: pd.DataFrame) -> Dict[str, float]:
        if df.empty:
            return {}
        category_totals = df.groupby("category")["amount"].sum()
        total = category_totals.sum()
        distribution = {
            cat: round((amount / total) * 100, 2) for cat, amount in category_totals.items()
        }
        return dict(sorted(distribution.items(), key=lambda x: x[1], reverse=True))

    def _get_most_supported_category(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty:
            return {
                "category": "None",
                "percentage": 0.0,
                "growth_percentage": 0.0,
                "total_invested": 0.0,
            }
        try:
            current_month = datetime.now().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            current_month_ts = pd.Timestamp(current_month)
            if (
                not df.empty
                and hasattr(df["created_at"].iloc[0], "tz")
                and df["created_at"].iloc[0].tz is not None
            ):
                current_month_ts = current_month_ts.tz_localize("UTC").tz_convert(
                    df["created_at"].iloc[0].tz
                )

            current_data = df[df["created_at"] >= current_month_ts]
            source = current_data if not current_data.empty else df
            category_totals = source.groupby("category")["amount"].sum()
            if category_totals.empty:
                return {
                    "category": "None",
                    "percentage": 0.0,
                    "growth_percentage": 0.0,
                    "total_invested": 0.0,
                }

            most = category_totals.idxmax()
            total_all = source["amount"].sum()
            percentage = (category_totals.max() / total_all * 100) if total_all > 0 else 0

            previous_month = (current_month - timedelta(days=1)).replace(day=1)
            previous_month_ts = pd.Timestamp(previous_month)
            if (
                not df.empty
                and hasattr(df["created_at"].iloc[0], "tz")
                and df["created_at"].iloc[0].tz is not None
            ):
                previous_month_ts = previous_month_ts.tz_localize("UTC").tz_convert(
                    df["created_at"].iloc[0].tz
                )
            prev_data = df[
                (df["created_at"] >= previous_month_ts)
                & (df["created_at"] < current_month_ts)
            ]
            growth = self._calculate_category_growth(str(most), source, prev_data)

            return {
                "category": str(most),
                "percentage": round(float(percentage), 2),
                "growth_percentage": round(float(growth), 2),
                "total_invested": round(float(category_totals.max()), 2),
            }
        except Exception as e:
            logger.error(f"Error in _get_most_supported_category: {e}")
            return {
                "category": "None",
                "percentage": 0.0,
                "growth_percentage": 0.0,
                "total_invested": 0.0,
            }

    def _calculate_category_growth(
        self, category: str, current_data: pd.DataFrame, prev_data: pd.DataFrame
    ) -> float:
        try:
            current_amount = current_data[current_data["category"] == category]["amount"].sum()
            prev_amount = prev_data[prev_data["category"] == category]["amount"].sum()
            if prev_amount == 0:
                return 100.0 if current_amount > 0 else 0.0
            return ((current_amount - prev_amount) / prev_amount) * 100
        except Exception:
            return 0.0

    def _get_frequency_trend(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty:
            return {
                "trend": "stable",
                "change_percentage": 0,
                "average_monthly_investments": 0,
            }
        df_sorted = df.sort_values("created_at")
        df_sorted["month"] = df_sorted["created_at"].dt.to_period("M")
        monthly_counts = df_sorted.groupby("month").size()
        if len(monthly_counts) < 2:
            return {
                "trend": "stable",
                "change_percentage": 0,
                "average_monthly_investments": round(
                    monthly_counts.iloc[0] if len(monthly_counts) == 1 else 0, 2
                ),
            }
        x = np.arange(len(monthly_counts))
        y = monthly_counts.values
        slope = np.polyfit(x, y, 1)[0]
        avg = np.mean(y)
        change = (slope / avg) * 100 if avg else 0
        trend = "increasing" if slope > 0.1 else "decreasing" if slope < -0.1 else "stable"
        return {
            "trend": trend,
            "change_percentage": round(change, 2),
            "average_monthly_investments": round(avg, 2),
        }

    def _calculate_impact_score(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty:
            return {
                "score": 0,
                "level": "Beginner",
                "factors": {
                    "total_amount": 0.0,
                    "consistency": 0.0,
                    "diversity": 0.0,
                    "recent_activity": 0.0,
                    "average_size": 0.0,
                },
            }
        factors = {}
        total_amount = df["amount"].sum()
        factors["total_amount"] = min(total_amount / 10, 100)
        df["month"] = df["created_at"].dt.to_period("M")
        factors["consistency"] = min(df["month"].nunique() * 15, 100)
        factors["diversity"] = min(df["category"].nunique() * 25, 100)
        three_months_ago = datetime.now() - timedelta(days=90)
        if hasattr(df["created_at"].iloc[0], "tz"):
            three_months_ago = pd.Timestamp(three_months_ago).tz_localize(
                df["created_at"].iloc[0].tz
            )
        recent = df[df["created_at"] >= three_months_ago]
        factors["recent_activity"] = min(len(recent) * 20, 100)
        factors["average_size"] = min(df["amount"].mean() * 2, 100)
        weights = {
            "total_amount": 0.3,
            "consistency": 0.25,
            "diversity": 0.2,
            "recent_activity": 0.15,
            "average_size": 0.1,
        }
        total_score = sum(factors[k] * w for k, w in weights.items())
        if total_score >= 80:
            level = "Whale"
        elif total_score >= 60:
            level = "Growth"
        elif total_score >= 40:
            level = "Investor"
        elif total_score >= 20:
            level = "Starter"
        else:
            level = "Beginner"
        return {
            "score": round(total_score),
            "level": level,
            "factors": {k: round(v, 2) for k, v in factors.items()},
        }

    def _get_monthly_trends(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        if df.empty:
            return []
        df = df.copy()
        df["month"] = df["created_at"].dt.to_period("M")
        monthly = df.groupby("month").agg(total=("amount", "sum"), count=("id", "count"))
        trends = []
        for month, row in monthly.iterrows():
            count = int(row["count"])
            total = float(row["total"])
            trends.append(
                {
                    "month": str(month),
                    "total_invested": total,
                    "investment_count": count,
                    "average_investment": total / count if count else 0,
                }
            )
        return trends[-6:]

    async def _get_recommended_products(
        self, user_id: UUID, df: pd.DataFrame, db: Session
    ) -> List[Dict[str, Any]]:
        def _row(project, reason):
            apy = getattr(project, "expected_apy", None)
            risk = project.risk_level.value if getattr(project, "risk_level", None) else None
            return {
                "id": str(project.id),
                "title": project.title,
                "category": project.category,
                "description": (
                    project.description[:100] + "..."
                    if len(project.description) > 100
                    else project.description
                ),
                "amount_raised": project.amount_raised,
                "target_amount": project.target_amount,
                "completion_percentage": round(
                    (project.amount_raised / project.target_amount) * 100, 2
                )
                if project.target_amount
                else 0,
                "expected_apy": apy,
                "risk_level": risk,
                "reason": reason,
            }

        if not df.empty:
            user_categories = (
                df.groupby("category")["amount"].sum().nlargest(3).index.tolist()
            )
            invested_ids = df["project_id"].tolist()
            recommended = (
                db.query(Project)
                .filter(
                    Project.verified == True,
                    Project.category.in_(user_categories),
                    ~Project.id.in_(invested_ids),
                )
                .order_by(Project.amount_raised.desc())
                .limit(5)
                .all()
            )
            if recommended:
                return [
                    _row(p, f"Matches your interest in {p.category}") for p in recommended
                ]

        popular = (
            db.query(Project)
            .filter(Project.verified == True)
            .order_by(Project.amount_raised.desc())
            .limit(5)
            .all()
        )
        return [_row(p, "Popular investment product on the platform") for p in popular]

    def _calculate_user_percentile(
        self, user_id: UUID, df: pd.DataFrame, db: Session
    ) -> Dict[str, Any]:
        all_inv = (
            db.query(Investment).filter(Investment.status.in_(ACTIVE_STATUSES)).all()
        )
        if not all_inv:
            return {
                "percentile": 100,
                "rank": 1,
                "total_investors": 1,
                "description": "Top investor",
            }

        totals = {}
        for inv in all_inv:
            key = str(inv.investor_id)
            totals[key] = totals.get(key, 0) + inv.amount

        user_total = df["amount"].sum()
        sorted_totals = sorted(totals.values(), reverse=True)
        try:
            rank = sorted_totals.index(user_total) + 1
        except ValueError:
            rank = len(sorted_totals)
        percentile = (rank / len(sorted_totals)) * 100
        if percentile <= 10:
            description = "Top 10% of investors"
        elif percentile <= 25:
            description = "Top 25% of investors"
        elif percentile <= 50:
            description = "Top 50% of investors"
        else:
            description = "Growing portfolio"
        return {
            "percentile": round(100 - percentile, 2),
            "rank": rank,
            "total_investors": len(totals),
            "description": description,
        }

    def _get_investment_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty:
            return {
                "total_invested": 0,
                "total_investments": 0,
                "average_investment": 0,
                "largest_investment": 0,
                "first_investment": None,
                "last_investment": None,
            }
        return {
            "total_invested": round(df["amount"].sum(), 2),
            "total_investments": len(df),
            "average_investment": round(df["amount"].mean(), 2),
            "largest_investment": round(df["amount"].max(), 2),
            "first_investment": df["created_at"].min().isoformat(),
            "last_investment": df["created_at"].max().isoformat(),
        }

    def _get_empty_insights(self) -> Dict[str, Any]:
        return {
            "category_distribution": {},
            "most_supported_category": {
                "category": "None",
                "percentage": 0.0,
                "growth_percentage": 0.0,
                "total_invested": 0.0,
            },
            "investment_frequency_trend": {
                "trend": "stable",
                "change_percentage": 0.0,
                "average_monthly_investments": 0.0,
            },
            "investor_score": {
                "score": 0,
                "level": "Beginner",
                "factors": {
                    "total_amount": 0.0,
                    "consistency": 0.0,
                    "diversity": 0.0,
                    "recent_activity": 0.0,
                    "average_size": 0.0,
                },
            },
            "monthly_trends": [],
            "recommended_products": [],
            "user_percentile": {
                "percentile": 0.0,
                "rank": 0,
                "total_investors": 0,
                "description": "New investor",
            },
            "investment_summary": {
                "total_invested": 0.0,
                "total_investments": 0,
                "average_investment": 0.0,
                "largest_investment": 0.0,
                "first_investment": None,
                "last_investment": None,
            },
            "message": "Start investing to unlock personalized portfolio insights!",
        }


