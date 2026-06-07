from fastapi import APIRouter, Depends, Request

from apps.api.dependencies import get_compliance_agent
from apps.api.limiter import limiter
from core.models import ChatRequest
from llm.agent import ComplianceAgent

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
@limiter.limit("10/minute")
async def chat(request: Request, req: ChatRequest, agent: ComplianceAgent = Depends(get_compliance_agent)):
    answer = await agent.answer(req.message)
    return {"answer": answer}
