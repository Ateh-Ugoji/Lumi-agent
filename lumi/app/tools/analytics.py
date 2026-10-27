from app.services.analytics import get_profile_analytics
from app.tools.registry import tool


@tool(
    name="get_analytics",
    description=(
        "Fetch the creator profile's live post impressions, reach trends, engagement statistics, and content format allocation. "
        "Use this tool whenever the user asks about their impressions, reach, analytics, metrics, or performance."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {
                "type": "integer",
                "description": (
                    "The profile ID to fetch analytics for. "
                    "Omit it — it defaults to the current chat profile."
                ),
            },
        },
    },
    side_effects="writes_db",
)
async def get_analytics(profile_id: int) -> dict:
    return await get_profile_analytics(profile_id)
