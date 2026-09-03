"""Boundary for future Michoe AI and association-rule recommendations.

No recommendations are fabricated here.  The service intentionally exposes a
stable seam for a future model once the business chooses an implementation.
"""

from services.analytics_service import AnalyticsService


class RecommendationService:
    """Placeholder boundary for future AI sales advice and Apriori analysis."""

    def __init__(self, analytics: AnalyticsService | None = None):
        self.analytics = analytics or AnalyticsService()

    def get_sales_advisor_context(self) -> dict:
        """Return factual data only; a model can consume this later."""
        return {
            "top_products": self.analytics.get_top_products(limit=10),
            "inventory": self.analytics.get_inventory_summary(),
            "brands": self.analytics.get_brand_sales(limit=10),
            "vehicles": self.analytics.get_vehicle_sales(),
        }

    def get_association_rules(self) -> list[dict]:
        """Reserved for Apriori support/confidence/lift results."""
        return []
