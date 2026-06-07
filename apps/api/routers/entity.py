from fastapi import APIRouter, Depends

from apps.api.dependencies import get_exposure_service, get_graph_repo
from graph.exposure_service import ExposureService
from graph.redis_graph_repository import RedisGraphRepository

router = APIRouter(prefix="/entity", tags=["entity"])


@router.get("/{entity_id}")
def entity_profile(
    entity_id: str,
    graph: RedisGraphRepository = Depends(get_graph_repo),
):
    return graph.get_entity_profile(entity_id)


@router.get("/{entity_id}/exposure")
def entity_exposure(
    entity_id: str,
    exposure: ExposureService = Depends(get_exposure_service),
):
    return exposure.get_exposure(entity_id)
