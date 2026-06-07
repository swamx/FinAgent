from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from apps.api.dependencies import get_retrieval_service
from apps.api.limiter import limiter
from vector.retriever import RetrievalService

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


@router.post("")
@limiter.limit("60/minute")
def search(
    request: Request,
    req: SearchRequest,
    retrieval: RetrievalService = Depends(get_retrieval_service),
):
    return retrieval.search(req.query, req.limit)
