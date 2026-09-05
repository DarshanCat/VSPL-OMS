from typing import Optional, List, Any
from pydantic import BaseModel

class AIQueryRequest(BaseModel):
    query: str
    context: Optional[dict[str, Any]] = None

class AIQueryResponse(BaseModel):
    query: str
    answer: str
    category: str  # "tracking" | "bottleneck" | "quality" | "planning" | "general"
    data_points: Optional[dict[str, Any]] = None
    suggested_actions: Optional[List[str]] = None

class AIInsightItem(BaseModel):
    type: str  # "risk" | "bottleneck" | "quality" | "optimization"
    title: str
    severity: str  # "high" | "medium" | "low" | "info"
    description: str
    impacted_entity: Optional[str] = None
    recommended_action: str

class AIInsightsResponse(BaseModel):
    generated_at: str
    insights: List[AIInsightItem]
