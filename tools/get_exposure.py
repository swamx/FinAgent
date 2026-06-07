from graph.exposure_service import ExposureService


def get_exposure(exposure: ExposureService, entity_id: str) -> str:
    return str(exposure.get_exposure(entity_id))
