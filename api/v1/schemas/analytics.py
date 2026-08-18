from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime


class CategoryDistribution(BaseModel):
    category: str
    percentage: float
    amount: float


class MostSupportedCategory(BaseModel):
    category: str
    percentage: float
    growth_percentage: float
    total_invested: float


class FrequencyTrend(BaseModel):
    trend: str  # "increasing", "decreasing", "stable"
    change_percentage: float
    average_monthly_investments: float


class ImpactFactors(BaseModel):
    total_amount: float
    consistency: float
    diversity: float
    recent_activity: float
    average_size: float


class ImpactScore(BaseModel):
    score: int
    level: str  # Beginner, Starter, Investor, Growth, Whale
    factors: ImpactFactors


class MonthlyTrend(BaseModel):
    month: str
    total_invested: float
    investment_count: int
    average_investment: float


class RecommendedProduct(BaseModel):
    id: str
    title: str
    category: str
    description: str
    amount_raised: float
    target_amount: float
    completion_percentage: float
    expected_apy: Optional[float] = None
    risk_level: Optional[str] = None
    reason: str


class UserPercentile(BaseModel):
    percentile: float
    rank: int
    total_investors: int
    description: str


class InvestmentSummary(BaseModel):
    total_invested: float
    total_investments: int
    average_investment: float
    largest_investment: float
    first_investment: Optional[str]
    last_investment: Optional[str]


class UserInsights(BaseModel):
    category_distribution: Dict[str, float]
    most_supported_category: MostSupportedCategory
    investment_frequency_trend: FrequencyTrend
    investor_score: ImpactScore
    monthly_trends: List[MonthlyTrend]
    recommended_products: List[RecommendedProduct]
    user_percentile: UserPercentile
    investment_summary: InvestmentSummary
    message: Optional[str] = None


class UserInsightsResponse(BaseModel):
    user_id: str
    user_email: str
    insights: UserInsights


class GlobalStats(BaseModel):
    total_investments: int
    total_capital_raised: float
    total_products: int
    total_investors: int
    average_investment: float


class CategoryAnalytics(BaseModel):
    category: str
    total_raised: float
    product_count: int
    investment_count: int
    average_investment: float
    percentage_of_total: float


class PlatformAnalytics(BaseModel):
    global_stats: GlobalStats
    top_categories: List[CategoryAnalytics]
    recent_activity: Dict[str, Any]


class ProductAnalytics(BaseModel):
    product_id: str
    product_title: str
    total_raised: float
    investment_count: int
    average_investment: float
    completion_percentage: float
    investor_count: int
    recent_investments: List[Dict[str, Any]]
