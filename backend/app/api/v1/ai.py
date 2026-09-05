from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.ai import AIQueryRequest, AIQueryResponse, AIInsightsResponse
from app.services.ai_service import AIService

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

@router.post("/query", response_model=AIQueryResponse)
def query_ai_assistant(
    payload: AIQueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Answer natural language manufacturing queries grounded on live shop-floor data."""
    return AIService.answer_query(db, payload)

@router.get("/insights", response_model=AIInsightsResponse)
def get_ai_insights(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve proactive AI insights: delivery risk warnings, WIP bottlenecks, and quality alerts."""
    return AIService.get_proactive_insights(db)
